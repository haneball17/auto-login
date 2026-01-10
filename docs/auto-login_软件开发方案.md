# Windows11 游戏自动登录与签到自动化项目（MVP）软件开发方案

> 目标：在 Windows11 环境下使用 Python 开发一个自动化项目，支持**每日两次登录周期**（间隔≥1.5小时）、支持**账号池轮换**、支持**网页登录**、支持**游戏客户端自动操作**（频道选择→角色选择→进入游戏→等待30秒→退出），并具备完善的日志、错误处理与证据留存能力。
> 备注：本项目属于游戏自动化行为，可能违反游戏服务条款，有封号风险，请自行评估。

---

## 1. 需求分析与验证

### 1.1 背景与业务目标

你需要在游戏中每日上线签到（在线时长1个半小时拿满奖励），每次登录流程包含：

1. 启动登录器 EXE
2. 等待登录器“启动”按钮可用（由灰转蓝）
3. EXE 拉起网页登录页
4. 输入账号密码点击登录
5. 等待游戏客户端启动并加载至频道选择界面
6. 在频道选择界面选择频道进入角色选择界面
7. 选择角色进入游戏界面
8. 等待30秒退出游戏
9. 完成一次账号的“登录周期”

### 1.2 MVP 功能要求（确认）

- **每日两次上线周期**（配置化），两次间隔 ≥ 90 分钟（可配置）
- **定时策略**：默认早上 07:00 ± 3 分钟、下午 13:00 ± 3 分钟随机执行；支持切换为固定时间模式（可配置）
- **账号池支持**：一次登录周期内按账号池轮流执行，直到所有账号执行过一次
- **失败重试**：单账号失败最大重试 2 次（可配置）
- **代码风格**：遵循 PEP 8 代码风格规范
- **频道选择策略**：频道界面前三个频道中随机选择一个
- **角色选择策略**：固定选择第一个角色
- **退出策略**：优先支持 Alt+F4（可配置），失败时允许强制结束进程；不计划短期内实现“结束游戏”按钮
- **Windows11 + Python 实现**（Linux 仅保证测试可运行）
- **完整日志与错误处理**：每一步有超时控制；出错保存证据（截图/堆栈/步骤上下文/网页 HTML dump）；不允许流程“无限卡死”

### 1.3 设想验证

你提出需要“结构完整”的方案是正确的：  

该项目不是一次性脚本，而是长期稳定运行的自动化系统，必须从开始就具备工程结构、可配置、可恢复、可排查与可扩展能力。

---

## 2. 技术路线选择

### 2.1 推荐总体方案（MVP）

✅**Playwright（网页登录） + OpenCV（模板匹配识别界面） + PyAutoGUI（鼠标键盘动作） + APScheduler（调度） + psutil/win32（进程与窗口管理）**

**选择理由：**
- 登录页无验证码/二次验证，且 HTML 已知，可通过稳定 selector 自动登录（ `#u` , `#p` , `#btn` ）
- 游戏 UI 固定且分辨率固定（默认 1920×1440，可配置），适合 OpenCV 模板匹配作为状态识别锚点
- 窗口模式可固定窗口位置/大小，使坐标点击稳定
- 全 Python 技术栈，便于工程化开发与部署
- 可实现完善日志、错误处理与证据留存

---

## 3. 轻量架构设计（Architecture）

### 3.1 简化结构

项目分为两块，避免过度抽象：

1. **调度与流程（runner）** - 读取配置、生成随机或固定执行时间、执行账号轮换与流程推进、失败重试
2. **执行与支撑（ops）** - Web 登录、界面识别与点击、进程与窗口控制、日志与证据留存

---

## 4. 模块设计与职责拆分（精简版）

以“少文件、少抽象、函数直观”为目标，尽量合并模块。

建议目录结构如下（MVP，精简，根目录直接放置）：
``` python
.
├─ pyproject.toml
├─ poetry.lock
├─ README.md
├─ config.yaml
├─ .env
├─ anchors/
│  ├─ channel_title.png
│  ├─ launcher_start_enabled.png
│  ├─ role_title.png
│  └─ in_game_right_icons.png
├─ logs/
│  └─ 2025-01-01.log
├─ evidence/
│  └─ 2025-01-01_1/
│     └─ a001/
│        └─ step_web_login/
│           ├─ screenshot.png
│           ├─ page.html
│           └─ trace.txt
├─ data/
│  ├─ state.json
│  └─ stop.flag
├─ src/
│  ├─ __init__.py
│  ├─ main.py
│  ├─ ui.py
│  ├─ config.py
│  ├─ runner.py
│  ├─ state.py
│  ├─ web_login.py
│  ├─ ui_ops.py
│  ├─ process_ops.py
│  ├─ evidence.py
│  └─ logger.py
└─ tests/
   ├─ test_config.py
   ├─ test_state.py
   ├─ test_schedule.py
   └─ test_match.py
```

模块职责（精简说明）：

- config.py：加载 config.yaml，用 .env 覆盖同名字段；完成基础校验
- runner.py：调度（随机窗口/固定时间）、互斥锁、cycle\_id、账号轮换、流程推进、失败重试，支持 stop.flag 优雅停止
- state.py：state.json 读写，记录完成/失败账号与重试次数
- web\_login.py：Playwright 登录与成功判定，失败证据留存
- ui\_ops.py：窗口定位、截图、模板匹配、点击/热键，含启动器按钮可用检测
- process\_ops.py：启动器启动、进程等待、强制结束
- evidence.py：截图/HTML/堆栈留存，保留 7 天并定期清理
- logger.py：日志初始化与统一格式，日志按日期分割保存到 logs/YYYY-MM-DD.log
- ui.py：PyQt6 前端入口（配置编辑、执行控制、状态/日志查看）

实现原则（精简风格）：
- 以函数为主，尽量扁平化，避免不必要的类与层级
- 仅在代码变复杂时再拆分文件
---

## 5. 关键流程设计（状态机推进）

### 5.1 界面状态锚点（anchors）

只用锚点判断“当前在哪个界面”，不依赖按钮模板：

- **频道选择界面** ： `anchors/channel_title.png` （裁剪“选择频道”）
- **角色选择界面** ： `anchors/role_title.png` （裁剪“选择角色”）
- **进入游戏界面** ： `anchors/in_game_right_icons.png` （裁剪右侧图标栏）
- **启动器按钮可用** ： `anchors/launcher_start_enabled.png`（蓝色“启动”按钮模板）
- 需要在当前分辨率与 DPI 下重新截取锚点图片

### 5.2 频道随机选择策略

在频道选择界面：

- 前三项频道区域设定为 3 个固定点击点（例如区域中心点）
- 每次随机选择其中一个点点击
- 点击后点击“游戏开始”
- 频道/角色/开始按钮的坐标或 ROI 在同一分辨率下固定

随机选择应具备“确定性可复现”能力（日志记录随机种子或选择结果）：

- 日志：记录选择了第几个频道（1/2/3）

### 5.3 角色选择策略

角色界面：

- 固定点击第一个角色槽位位置
- 点击“游戏开始”

---

## 6. 可靠性设计（日志、超时、重试、恢复）

### 6.1 超时与重试矩阵（建议默认值）

优先使用统一默认值，关键步骤再单独覆盖。

| Step | 超时 | 重试 | 失败处理 |
| --- | --- | --- | --- |
| 启动 launcher | 30s | 1 | 记录失败，跳过该账号 |
| 等待启动按钮可用 | 60s | 2 | 保存截图，重启 launcher |
| Web 登录 | 60s | 2 | 保存 HTML + 截图，尝试重启 launcher |
| 等游戏进程 | 120s | 1 | 强制结束残留进程后重试 |
| 等频道界面 | 120s | 2 | 保存截图，尝试回到上一阶段或重启 |
| 选频道/开始 | 20s | 3 | 保存截图，重新点击 |
| 等角色界面 | 120s | 2 | 保存截图，重启账号流程 |
| 选角色/开始 | 20s | 3 | 保存截图，重新点击 |
| 等进入游戏 | 120s | 2 | 保存截图，重启账号流程 |
| 游戏内等待 | 30s | 0 | \- |
| 退出游戏 | 20s | 1 | 若失败则强制结束进程 |

> 目标：任何一步都不能无限等待，必须可退出与可继续。

### 6.2 故障隔离策略

- 单个账号失败不会导致整个 cycle 崩溃
- cycle 结束后输出 summary
- 对失败账号进行记录并在下一次周期继续尝试（可配置）
- 单账号失败最大重试 2 次（可配置）

### 6.3 防重入/防并发

- Scheduler 触发时加锁（文件锁或进程锁）
- 若锁被占用则跳过本次或延迟（可配置）

---

## 7. 配置设计（config.yaml）

配置包含：

- schedule：调度策略（固定时间或随机窗口）、最小间隔
- accounts：账号池
- launcher：启动器路径、进程名、窗口标题关键字
- web：登录 URL 与 selector、成功判定 selector
- flow：超时/重试/模板阈值/随机策略/退出策略/账号最大重试
- window：位置与尺寸、分辨率与 DPI
- evidence：保存路径与保留天数

使用 pydantic-settings 从 .env 覆盖同名字段（默认规则，嵌套字段使用 `__`）。

示例字段（概念级）：
``` yaml
schedule:
  mode: "random_window" # 默认 random_window，可切换 fixed_times
  min_gap_minutes: 90
  random_windows:
    - center: "07:00"
      jitter_minutes: 3
    - center: "13:00"
      jitter_minutes: 3
  fixed_times:
    - "07:00"
    - "13:00"

launcher:
  exe_path: "D:/game/猪咪云DNF-auto/猪咪启动器.exe"
  game_process_name: "DNF Taiwan"
  game_window_title_keyword: "DNF Taiwan"

web:
  login_url: "https://xxx/login"
  username_selector: "#u"
  password_selector: "#p"
  login_button_selector: "#btn"
  success_selector: "#startGame"

accounts:
  pool:
    - username: "a001"
      password: "p001"
    - username: "a002"
      password: "p002"

flow:
  step_timeout_seconds: 120
  click_retry: 3
  template_threshold: 0.86
  enter_game_wait_seconds: 30
  channel_random_range: 3
  force_kill_on_exit_fail: true
  account_max_retry: 2

window:
  x: 0
  y: 0
  width: 1920
  height: 1440
  dpi_scale_percent: 150

evidence:
  dir: "evidence"
  retention_days: 7
```
---

## 8. 前端设计（PyQt6）

目标：仅覆盖“基础设置 + 执行控制 + 状态/日志浏览”，避免复杂交互。

### 8.1 界面结构

- 主窗口：QMainWindow + QTabWidget
- 设置页：原始 YAML 编辑器（QPlainTextEdit），支持“加载/保存/语法校验提示”，仅编辑 config.yaml
- 执行页：显示当前周期、下次执行、当前账号、当前步骤、完成/失败统计；提供“开始/停止/强制停止/立即执行一次”按钮
- 日志页：日志文件选择（按日期）、关键词过滤、实时滚动、打开证据文件夹按钮

### 8.2 行为约定（简化）

- 开始：若 runner 未运行，则启动 `python -m src.main`
- 停止：写入 stop.flag，runner 在安全点检测后优雅退出
- 强制停止：若仍在运行，直接结束进程
- 立即执行一次：调用 `python -m src.main --once`（M3 完成后）
- 状态刷新与日志滚动使用 QTimer 轮询，避免复杂线程

## 9. 测试方案（保障可维护性）

### 9.1 单元测试（不依赖游戏）

- 配置加载与校验（YAML + .env）
- state.json 写入/读取
- 调度时间与间隔校验（固定时间/随机窗口）
- 模板匹配接口（用静态截图）
- Windows 环境下覆盖所有模块，不使用 mock
- Linux 环境下保证测试可运行（Windows 专用模块可自动跳过）

### 9.2 集成测试（需要游戏）

- 在频道界面执行 wait\_anchor(channel)
- 在角色界面执行 wait\_anchor(role)
- 在游戏内执行 wait\_anchor(in\_game)

### 9.3 E2E 测试（完整链路）

- 使用测试账号跑完整流程
- 检查日志完整性
- 检查 evidence 输出
- 确认退出后进程不存在

---

## 10. 部署与运行

### 10.1 MVP 运行方式

- 采用常驻方式运行： `python -m src.main`（由 APScheduler 负责调度）
- 如需系统任务计划，仅用于拉起常驻进程，不承担调度逻辑
- 依赖管理使用 Poetry（pyproject.toml）
- 启动前端： `python -m src.ui`（M5 完成后）
- 注意：必须在有桌面会话的用户环境运行（UI 自动化依赖桌面）

### 10.2 环境约束

必须满足：

- 分辨率与 DPI 与配置保持一致（默认 1920×1440、150%，可配置）
- 游戏窗口固定位置/大小（配置化，允许变化）
- 运行期间避免用户操作鼠标键盘（降低误操作）
- 实际运行仅支持 Windows11（Linux 仅保证测试可运行）

---

## 11. 可扩展规划（非 MVP）

后续可加入：

- 失败通知（邮件/微信/Telegram）
- 自适应点击（通过模板定位按钮中心点击）
- 退出游戏时支持“结束游戏按钮”（实现预留接口）
- 运行录像（可选）
- 状态存储升级 sqlite
- GUI 配置界面（可选）

---

## 12. 里程碑计划（建议）

### Milestone 1：工程骨架 + 配置 + 日志 + 调度（0.5 天）

- config.yaml
- logger/evidence
- runner（含调度） + lock
- state.json 管理

### Milestone 2：游戏端识别与推进（1 天）

- anchors 制作
- wait\_anchor + click 推进
- 三界面成功识别
- 能进入游戏并退出

### Milestone 3：网页登录接入（0.5 天）

- Playwright 登录
- 等待游戏启动

### Milestone 4：账号池轮换 + 完整 E2E（0.5 天）

- 多账号轮流执行
- 失败留证
- E2E 稳定性验证

> 预计 2~3 天可完成 MVP。

---

## 13. 关键设计决策总结

- **状态识别优先使用锚点模板** （界面标题/固定图标区域），避免按钮 hover/亮度变化导致误判
- **动作采用固定坐标点击** （在分辨率固定情况下稳定且实现简单）
- **频道选择随机化** ：前三个频道随机选一个，并记录选择结果便于回溯
- **调度策略**：默认 07:00±3 分钟、13:00±3 分钟随机执行，同时支持固定时间模式
- **配置方案**：config.yaml + pydantic-settings + .env（默认规则）
- **实现风格**：优先简单清晰的函数结构，避免不必要的复杂抽象
- **退出策略**：优先 Alt+F4，失败时强制结束进程，不计划短期内实现“结束游戏”按钮
- **账号重试**：单账号失败最大重试 2 次（可配置）
- **每一步必须有 timeout + retry + evidence** ，确保系统可恢复、可排查、不会卡死
- **账号池支持断点续跑** ，降低长期运行维护成本
