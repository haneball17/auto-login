# auto-login 状态机说明（基于当前代码实现）

> 版本基线：按当前仓库代码（`src/main.py`、`src/scheduler.py`、`src/runner.py`、`src/web_login.py`）整理。  
> 说明重点：这里的“状态机”不是单一 `enum`，而是**多层级状态机协作**。

## 1. 总览：四层状态机

当前系统可拆成 4 层状态机：

1. 入口与模式选择状态机（CLI）
2. 调度状态机（常驻调度、加锁、防并发）
3. 账号执行状态机（账号轮换、重试、断点、停止）
4. 场景状态机（频道/角色/进游戏识别与异常恢复）

---

## 2. 入口与模式选择状态机

核心代码：`src/main.py:62`。

```mermaid
stateDiagram-v2
    [*] --> 解析参数
    解析参数 --> 加载配置与锚点校验

    加载配置与锚点校验 --> 启动器单步: --launcher-only
    加载配置与锚点校验 --> 启动器+网页登录: --launcher-web-login
    加载配置与锚点校验 --> 单次全账号: --once
    加载配置与锚点校验 --> 调度常驻: 默认模式

    启动器单步 --> [*]: run_launcher_flow
    启动器+网页登录 --> [*]: run_launcher_web_login_flow
    单次全账号 --> [*]: run_all_accounts_once
    调度常驻 --> [*]: run_scheduler(阻塞)
```

### 关键点

- `main` 在分流前统一完成配置加载和锚点存在性校验（`src/main.py:90`）。
- 默认不传模式参数时进入调度常驻（`src/main.py:70`、`src/main.py:119`）。

---

## 3. 调度状态机（Scheduler）

核心代码：`src/scheduler.py:70`。

```mermaid
stateDiagram-v2
    [*] --> 初始化调度器
    初始化调度器 --> 生成当天执行时刻
    生成当天执行时刻 --> 等待触发
    等待触发 --> 触发任务: 到达 DateTrigger

    触发任务 --> 检查线程锁
    检查线程锁 --> 跳过本次: _job_lock 已占用
    检查线程锁 --> 检查stop.flag: 获取锁成功

    检查stop.flag --> 跳过本次: stop.flag 存在
    检查stop.flag --> 检查文件锁: stop.flag 不存在

    检查文件锁 --> 跳过本次: run.lock 被占用
    检查文件锁 --> 执行一次全账号: 获得 run.lock

    执行一次全账号 --> 释放锁并结束任务
    跳过本次 --> 等待触发
    释放锁并结束任务 --> 等待触发

    等待触发 --> 次日重建计划: 每天 00:01
    次日重建计划 --> 生成当天执行时刻
```

### 关键点

- 双重防并发：
  - 进程内互斥锁 `_job_lock`（`src/scheduler.py:84`）。
  - 文件锁 `logs/run.lock`（`src/scheduler.py:91`）。
- 若计划时间已过，会“立即补跑一次”（`src/scheduler.py:126`）。
- 随机窗口使用日期种子保证“当天稳定可复现”（`src/scheduler.py:170`）。

---

## 4. 账号执行状态机（run_all_accounts_once）

核心代码：`src/runner.py:281`。

```mermaid
stateDiagram-v2
    [*] --> 加载可执行账号列表
    加载可执行账号列表 --> 读取断点state.json
    读取断点state.json --> 计算起始账号索引
    计算起始账号索引 --> 进入账号循环

    state 进入账号循环 {
        [*] --> 检查stop.flag_循环前
        检查stop.flag_循环前 --> 写入stopped并退出循环: stop.flag存在
        检查stop.flag_循环前 --> 写入running(当前index): stop.flag不存在

        写入running(当前index) --> 尝试执行账号(最多account_max_retry次)

        尝试执行账号(最多account_max_retry次) --> 账号成功
        尝试执行账号(最多account_max_retry次) --> 账号失败可重试: 普通异常且未超次数
        账号失败可重试 --> 尝试执行账号(最多account_max_retry次)

        尝试执行账号(最多account_max_retry次) --> 写入manual并返回: ManualInterventionRequired
        尝试执行账号(最多account_max_retry次) --> 超重试标记失败: 已超最大次数

        账号成功 --> 写入running(下一个index)
        超重试标记失败 --> 写入running(下一个index)

        写入running(下一个index) --> 等待下个账号
        等待下个账号 --> 检查stop.flag_等待期
        检查stop.flag_等待期 --> 写入stopped并退出循环: stop.flag存在
        检查stop.flag_等待期 --> [*]: 进入下一个账号
    }

    进入账号循环 --> 写入completed: 正常跑完且未stop
    进入账号循环 --> [*]: manual/stopped提前结束
    写入completed --> [*]
```

### `state.json` 状态语义

核心写入点：`src/runner.py:445`。

| status | 含义 | 典型写入位置 |
|---|---|---|
| `running` | 流程进行中，同时记录 `next_index` | 每个账号开始与结束后 |
| `stopped` | 检测到 `stop.flag` 后安全停止 | 循环前或账号间等待时 |
| `manual` | 触发人工介入策略，流程中止 | `ManualInterventionRequired` 或 `error_policy=manual` |
| `completed` | 当轮执行完成 | 全部账号结束后 |

### 断点恢复规则

核心代码：`src/runner.py:468`。

- `accounts_hash` 不一致：忽略断点，从头开始。
- `status=completed` 或 `next_index > total`：从头开始。
- 其他情况：从 `next_index` 对应账号恢复。

---

## 5. 单账号主流程状态机

核心入口：`src/runner.py:230`（`run_launcher_web_login_flow`）。

```mermaid
stateDiagram-v2
    [*] --> 启动器阶段
    启动器阶段 --> 等待登录URL
    等待登录URL --> 网页自动登录
    网页自动登录 --> 等待游戏窗口
    等待游戏窗口 --> 频道到角色阶段
    频道到角色阶段 --> 角色到进游戏阶段
    角色到进游戏阶段 --> 账号完成

    启动器阶段 --> 步骤失败: 启动器/按钮异常
    等待游戏窗口 --> 步骤失败: 超时或窗口异常
    频道到角色阶段 --> 步骤失败: 场景重试耗尽
    角色到进游戏阶段 --> 步骤失败: 场景重试耗尽

    等待登录URL --> 网页阶段失败恢复: URL捕获失败
    网页自动登录 --> 网页阶段失败恢复: Playwright失败/超时
    网页阶段失败恢复 --> 抛异常返回上层

    步骤失败 --> 抛异常返回上层
    账号完成 --> [*]
```

### 网页阶段失败恢复分叉

核心代码：`src/runner.py:194`。

- 固定动作：先保存证据。
- `error_policy=manual`：保留现场并返回异常。
- `error_policy=restart`：关闭浏览器窗口、杀浏览器进程、重置启动器，再抛异常回上层重试。

---

## 6. 场景状态机（频道/角色/进游戏）

场景检查器构建：`src/runner.py:490`。  
基础场景：

- `频道选择界面`
- `角色选择界面`
- `进入游戏界面`

### 6.1 通用等待状态机（模板优先 + 异常补偿）

核心代码：`src/runner.py:928`。

```mermaid
stateDiagram-v2
    [*] --> 循环匹配模板
    循环匹配模板 --> 命中期望场景: result.found
    循环匹配模板 --> 检查是否到异常窗口期: 未命中

    检查是否到异常窗口期 --> 继续模板轮询: 未到exception_delay
    检查是否到异常窗口期 --> 模板异常扫描: 已到exception_delay

    模板异常扫描 --> 返回场景: 扫描命中
    模板异常扫描 --> OCR异常扫描: 未命中

    OCR异常扫描 --> 返回场景: OCR命中并可归类
    OCR异常扫描 --> 继续模板轮询: OCR未命中

    循环匹配模板 --> 超时返回None: timeout

    命中期望场景 --> [*]
    返回场景 --> [*]
    超时返回None --> [*]
```

### 6.2 频道 -> 角色 子状态机

核心代码：`src/runner.py:1078`。

```mermaid
stateDiagram-v2
    [*] --> 预检测当前场景
    预检测当前场景 --> 已在角色或游戏: scene in {角色,进游戏}
    预检测当前场景 --> 等待频道标题: 否则

    等待频道标题 --> 超时重试: scene=None
    等待频道标题 --> 非期望场景分支: is_expected=False
    等待频道标题 --> 选择频道并点开始: is_expected=True

    非期望场景分支 --> 成功返回: scene in {角色,进游戏}
    非期望场景分支 --> 重试下一轮: 其他场景

    选择频道并点开始 --> 等待角色标题
    等待角色标题 --> 成功返回: scene=角色
    等待角色标题 --> 成功返回: scene=进游戏
    等待角色标题 --> 重试下一轮: 其他情况

    超时重试 --> 重试下一轮
    重试下一轮 --> [*]: 达到重试上限则失败
    已在角色或游戏 --> [*]
```

#### 频道选择内部刷新机（`_select_channel_with_refresh`）

```mermaid
stateDiagram-v2
    [*] --> 搜索可选频道
    搜索可选频道 --> 选中随机频道并开始: 找到>=1个
    搜索可选频道 --> 达到刷新上限: 未找到且次数耗尽
    搜索可选频道 --> 尝试处理频道异常提示: 未找到且可继续

    尝试处理频道异常提示 --> 点击刷新按钮
    点击刷新按钮 --> 搜索可选频道

    达到刷新上限 --> 结束游戏并失败
    选中随机频道并开始 --> [*]
    结束游戏并失败 --> [*]
```

### 6.3 角色 -> 进游戏 子状态机

核心代码：`src/runner.py:1154`。

```mermaid
stateDiagram-v2
    [*] --> 预检测是否已进游戏
    预检测是否已进游戏 --> 游戏内等待并退出: 已进游戏
    预检测是否已进游戏 --> 等待角色标题: 否则

    等待角色标题 --> 重试下一轮: 超时且仍未进游戏
    等待角色标题 --> 游戏内等待并退出: scene=进游戏
    等待角色标题 --> 选择角色并点开始: scene=角色

    选择角色并点开始 --> 等待进游戏双模板
    等待进游戏双模板 --> 游戏内等待并退出: scene=进游戏
    等待进游戏双模板 --> 重试下一轮: 其他情况

    重试下一轮 --> [*]: 达到重试上限则失败
    游戏内等待并退出 --> [*]
```

---

## 7. 失败与恢复状态机

### 7.1 通用步骤失败（`_handle_step_failure`）

核心代码：`src/runner.py:1743`。

```mermaid
stateDiagram-v2
    [*] --> 保存证据(ui_failure)
    保存证据(ui_failure) --> 抛ManualInterventionRequired: error_policy=manual
    保存证据(ui_failure) --> 抛RuntimeError: error_policy=restart
```

### 7.2 账号循环中的异常恢复（`run_all_accounts_once`）

核心代码：`src/runner.py:342`。

```mermaid
stateDiagram-v2
    [*] --> 捕获账号异常
    捕获账号异常 --> 保存runner_exception证据
    保存runner_exception证据 --> 强制退出游戏并重试: error_policy=restart
    保存runner_exception证据 --> 写manual并结束全流程: error_policy=manual
    强制退出游戏并重试 --> [*]
```

### 7.3 游戏退出策略（`_force_exit_game`）

核心代码：`src/runner.py:1417`。

```mermaid
stateDiagram-v2
    [*] --> 尝试关闭游戏窗口(WM_CLOSE)
    尝试关闭游戏窗口(WM_CLOSE) --> 等待进程退出
    等待进程退出 --> 成功结束: 已退出
    等待进程退出 --> 检查是否允许强杀: 未退出

    检查是否允许强杀 --> 记录告警并返回: force_kill_on_exit_fail=false
    检查是否允许强杀 --> kill_processes强杀: force_kill_on_exit_fail=true
    kill_processes强杀 --> 二次等待退出
    二次等待退出 --> 结束

    成功结束 --> [*]
    记录告警并返回 --> [*]
    结束 --> [*]
```

---

## 8. 登录 URL 捕获状态机（网页登录前置）

核心代码：`src/web_login.py:37`。

```mermaid
stateDiagram-v2
    [*] --> 轮询浏览器进程
    轮询浏览器进程 --> 从命令行提取URL: 检测到目标进程
    从命令行提取URL --> 捕获成功: 正则+参数校验通过
    从命令行提取URL --> 尝试剪贴板读取地址栏: 提取失败

    尝试剪贴板读取地址栏 --> 捕获成功: 剪贴板识别到URL
    尝试剪贴板读取地址栏 --> 继续轮询: 失败

    轮询浏览器进程 --> 超时失败: 超过timeout_seconds
    捕获成功 --> [*]
    超时失败 --> [*]
```

### 特点

- 命令行提取优先，剪贴板读取作为回退。
- 捕获成功后可按配置关闭登录页标签（`Ctrl+W`）。

---

## 9. `stop.flag` 对状态机的影响

`stop.flag` 是跨层“中断信号”：

- 调度层：任务触发前检查，存在则该次不启动（`src/scheduler.py:87`）。
- 账号层：
  - 进入账号前检查（`src/runner.py:307`）。
  - 账号间等待前再检查（`src/runner.py:402`）。
- 语义：**优雅停止**，不强行中断当前函数栈，而是在安全边界退出。

---

## 10. 你可以如何读这个状态机

建议按下面顺序对照源码阅读：

1. `src/main.py:62`（入口分流）
2. `src/scheduler.py:70`（调度触发与锁）
3. `src/runner.py:281`（账号循环主状态机）
4. `src/runner.py:230`（单账号主流程）
5. `src/runner.py:928`（模板等待+异常补偿）
6. `src/runner.py:1078` 与 `src/runner.py:1154`（场景推进）
7. `src/runner.py:1743`（统一失败出口）

---

## 11. 结论

当前项目状态机设计属于“**分层状态机 + 异常补偿闭环**”：

- 上层控制节奏（调度、轮换、重试、停止）。
- 下层控制场景收敛（模板优先 + OCR兜底 + 刷新重试）。
- 失败路径统一留证，并由 `error_policy` 决定“自动恢复”或“人工介入”。

