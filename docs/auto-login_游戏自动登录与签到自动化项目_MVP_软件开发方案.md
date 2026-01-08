# auto-login_游戏自动登录与签到自动化项目_MVP_软件开发方案

> 目标：在 Windows11 环境下使用 Python 开发一个自动化项目，支持**每日两次登录周期**（间隔≥1.5小时）、支持**账号池轮换**、支持**网页登录**、支持**游戏客户端自动操作**（频道选择→角色选择→进入游戏→等待30秒→退出），并具备完善的日志、错误处理与证据留存能力。
> 备注：本项目属于游戏自动化行为，可能违反游戏服务条款，有封号风险，请自行评估。

---

## 1. 需求分析与验证

### 1.1 背景与业务目标

你需要在游戏中每日上线签到（在线时长1个半小时拿满奖励），每次登录流程包含：

1) 启动登录器 EXE
2) EXE 拉起网页登录页
3) 输入账号密码点击登录
4) 等待游戏客户端启动并加载至频道选择界面
5) 在频道选择界面选择频道进入角色选择界面
6) 选择角色进入游戏界面
7) 等待30秒退出游戏
8) 完成一次账号的“登录周期”

### 1.2 MVP 功能要求（确认）

- **每日两次上线周期**（配置化），两次间隔 ≥ 90 分钟（可配置）
- **账号池支持**：一次登录周期内按账号池轮流执行，直到所有账号执行过一次
- **频道选择策略**：频道界面前三个频道中**随机选择一个**
- **角色选择策略**：固定选择第一个角色
- **退出策略**：优先支持 Alt+F4（可配置），并**预留“结束游戏”接口（暂不实现）**
- **Windows11 + Python 实现**
- 完整日志与错误处理：
  - 每一步有超时控制
  - 出错保存证据（截图/堆栈/步骤上下文/网页 HTML dump）
  - 不允许流程“无限卡死”

### 1.3 设想验证

你提出需要“结构完整”的方案是正确的：
该项目不是一次性脚本，而是长期稳定运行的自动化系统，必须从开始就具备工程结构、可配置、可恢复、可排查与可扩展能力。

---

## 2. 技术路线选择

### 2.1 推荐总体方案（MVP）

✅ **Playwright（网页登录） + OpenCV（模板匹配识别界面） + PyAutoGUI（鼠标键盘动作） + APScheduler（调度） + psutil/win32（进程与窗口管理）**

**选择理由：**

- 登录页无验证，且 HTML 已知，可通过稳定 selector 自动登录（`#u`, `#p`, `#btn`）
- 游戏 UI 固定且分辨率固定（1920×1440），适合 OpenCV 模板匹配作为状态识别锚点
- 窗口模式可固定窗口位置/大小，使坐标点击稳定
- 全 Python 技术栈，便于工程化开发与部署
- 可实现完善日志、错误处理与证据留存

---

## 3. 总体架构设计（Architecture）

### 3.1 分层架构

项目分为四层：

1) **调度层 Scheduler**

   - 读取配置并设置每日两次任务
   - 校验两次任务间隔 ≥ 90 分钟
   - 防止重入执行（锁机制）
2) **编排层 Orchestrator**

   - 负责一次登录周期内的账号池轮换执行
   - 支持断点恢复：记录本周期已完成账号
   - 失败策略：重试、跳过、继续下一个账号
3) **执行层 Automation Engine**

   - Web 登录自动化（Playwright）
   - 游戏客户端自动化（OpenCV+PyAutoGUI）
   - 进程与窗口控制（psutil+win32）
4) **基础设施层 Infra**

   - 配置管理（TOML + 校验）
   - 状态存储（state.json）
   - 日志系统（loguru / logging）
   - Evidence（截图、HTML dump、堆栈、上下文）
   - 通知接口（可选，MVP不做）

---

## 4. 模块设计与职责拆分

建议目录结构如下（MVP）：

```
auto_login/
  config.toml
  run.py
  anchors/
    channel_title.png
    role_title.png
    in_game_right_icons.png
  src/
    logger.py
    evidence.py
    config.py
    scheduler.py
    account_pool.py
    orchestrator.py
    flow.py
    web_login.py
    ui/
      match.py
      capture.py
      actions.py
      window.py
    process/
      launcher.py
      game_process.py
```

### 4.1 config.py（配置）

- 加载 config.toml
- 校验字段合法性：
  - schedule.times 格式正确
  - 两次上线间隔满足 min_gap_minutes
  - exe_path 存在
  - anchors 文件存在
  - 账号池不为空
- 输出统一配置对象（dataclass）

### 4.2 scheduler.py（调度）

- APScheduler cron 触发每日两次任务
- 触发时生成 cycle_id（例如 `20260108_1`、`20260108_2`）
- 任务互斥：使用文件锁/进程锁防止同一时间重复执行
- 支持 `--once` 参数手动触发一次（调试）

### 4.3 account_pool.py（账号池 & 状态）

- 管理账号池列表
- 维护 state.json：
  - cycle_id
  - accounts_done：本周期完成账号
  - accounts_failed：失败账号及原因
  - retry_count：账号重试次数
- 支持断点续跑：崩溃后重启可跳过已完成账号

### 4.4 web_login.py（网页登录）

- Playwright 启动/连接浏览器
- 打开登录 URL
- 通过 selector 执行：
  - fill `#u`（用户名）
  - fill `#p`（密码）
  - click `#btn`（登录）
- 登录成功判定：
  - 等待某个成功标志元素出现（配置化）
  - 或等待游戏启动按钮出现（配置化）
- 失败证据：
  - 保存页面 screenshot
  - 保存 page.content() HTML dump

### 4.5 flow.py（单账号完整流程）

定义单账号执行状态机，包括：

1) 启动 launcher.exe
2) web_login
3) wait_game_process
4) focus_game_window + 固定位置/尺寸
5) wait_channel_select（anchor）
6) 频道随机选择前三个之一 + 点击游戏开始
7) wait_role_select（anchor）
8) 选第一个角色 + 点击游戏开始
9) wait_in_game（anchor）
10) sleep 30秒
11) exit_game（Alt+F4）
12) 返回 success/fail

### 4.6 match.py（OpenCV 模板匹配）

- 对指定 ROI 截图
- template match（`cv2.matchTemplate`）
- 返回：
  - found（bool）
  - score（float）
  - center（坐标）
- 支持 threshold 可配置（默认 0.86~0.92）

### 4.7 actions.py（鼠标键盘动作封装）

- click(x, y)
- hotkey("alt", "f4")
- press("esc")
- 动作前强制窗口聚焦
- 支持 click 微扰（±2~3 px，可配置）
- 支持 click 重试（默认 3 次）

### 4.8 window.py（窗口定位与固定）

- Win32 API 查找窗口句柄
- 设置窗口到固定位置与大小（配置）
- 校验窗口分辨率（1920×1440）
- 确保窗口未最小化、可见

### 4.9 evidence.py（证据留存）

任何异常必须保存：

- 当前窗口截图（或全屏）
- 错误堆栈
- step 名称
- cycle_id / account_id
- （网页登录失败）HTML dump

目录结构建议：

```
evidence/
  20260108_1/
    a001/
      step_web_login/
        screenshot.png
        page.html
        trace.txt
      step_channel_select/
        screenshot.png
        trace.txt
```

---

## 5. 关键流程设计（状态机推进）

### 5.1 界面状态锚点（anchors）

只用锚点判断“当前在哪个界面”，不依赖按钮模板：

- **频道选择界面**：`anchors/channel_title.png`（裁剪“选择频道”）
- **角色选择界面**：`anchors/role_title.png`（裁剪“选择角色”）
- **进入游戏界面**：`anchors/in_game_right_icons.png`（裁剪右侧图标栏）

### 5.2 频道随机选择策略

在频道选择界面：

- 前三项频道区域设定为 3 个固定点击点（例如区域中心点）
- 每次随机选择其中一个点点击
- 点击后点击“游戏开始”

随机选择应具备“确定性可复现”能力（日志记录随机种子或选择结果）：

- 日志：记录选择了第几个频道（1/2/3）

### 5.3 角色选择策略

角色界面：

- 固定点击第一个角色槽位位置
- 点击“游戏开始”

---

## 6. 可靠性设计（日志、超时、重试、恢复）

### 6.1 超时与重试矩阵（建议默认值）


| Step          | 超时 | 重试 | 失败处理                            |
| --------------- | ------ | ------ | ------------------------------------- |
| 启动 launcher | 30s  | 1    | 记录失败，跳过该账号                |
| Web 登录      | 60s  | 2    | 保存 HTML + 截图，尝试重启 launcher |
| 等游戏进程    | 120s | 1    | terminate 残留进程后重试            |
| 等频道界面    | 120s | 2    | 保存截图，尝试回到上一阶段或重启    |
| 选频道/开始   | 20s  | 3    | 保存截图，重新点击                  |
| 等角色界面    | 120s | 2    | 保存截图，重启账号流程              |
| 选角色/开始   | 20s  | 3    | 保存截图，重新点击                  |
| 等进入游戏    | 120s | 2    | 保存截图，重启账号流程              |
| 游戏内等待    | 30s  | 0    | -                                   |
| 退出游戏      | 20s  | 1    | 若失败则 terminate                  |

> 目标：任何一步都不能无限等待，必须可退出与可继续。

### 6.2 故障隔离策略

- 单个账号失败不会导致整个 cycle 崩溃
- cycle 结束后输出 summary
- 对失败账号进行记录并在下一次周期继续尝试（可配置）

### 6.3 防重入/防并发

- Scheduler 触发时加锁（文件锁或进程锁）
- 若锁被占用则跳过本次或延迟（可配置）

---

## 7. 配置设计（config.toml）

配置包含：

- schedule：两次运行时间、最小间隔
- accounts：账号池
- launcher：路径与进程名
- web：登录 URL 与 selector、成功判定 selector
- flow：超时/重试/模板阈值/随机策略
- window：位置与尺寸（1920×1440）

示例字段（概念级）：

```toml
[schedule]
times = ["08:30", "22:10"]
min_gap_minutes = 90

[launcher]
exe_path = "D:\Game\Launcher.exe"
game_process_name = "DNF.exe"
game_window_title_keyword = "地下城与勇士"

[web]
login_url = "https://xxx/login"
username_selector = "#u"
password_selector = "#p"
login_button_selector = "#btn"
success_selector = "#startGame"

[accounts]
pool = [
  { username="a001", password="p001" },
  { username="a002", password="p002" }
]

[flow]
step_timeout_seconds = 120
click_retry = 3
template_threshold = 0.86
enter_game_wait_seconds = 30
channel_random_range = 3

[window]
x = 0
y = 0
w = 1920
h = 1440
dpi_scale_required = 100
```

---

## 8. 测试方案（保障可维护性）

### 8.1 单元测试（不依赖游戏）

- 配置加载与校验
- state.json 写入/读取
- 调度时间间隔校验
- 模板匹配接口（用静态截图）

### 8.2 集成测试（需要游戏）

- 在频道界面执行 wait_anchor(channel)
- 在角色界面执行 wait_anchor(role)
- 在游戏内执行 wait_anchor(in_game)

### 8.3 E2E 测试（完整链路）

- 使用测试账号跑完整流程
- 检查日志完整性
- 检查 evidence 输出
- 确认退出后进程不存在

---

## 9. 部署与运行

### 9.1 MVP 运行方式

- 推荐常驻方式运行：`python run.py`
- 或由 Windows Task Scheduler 每天启动一次 `run.py`，内部完成两次执行（需要进程保持）
- 注意：必须在有桌面会话的用户环境运行（UI 自动化依赖桌面）

### 9.2 环境约束

必须满足：

- 屏幕分辨率固定 1920×1440
- Windows 显示缩放 100%（必须）
- 游戏窗口固定位置/大小（建议放到屏幕左上角）
- 运行期间避免用户操作鼠标键盘（降低误操作）

---

## 10. 可扩展规划（非 MVP）

后续可加入：

- 失败通知（邮件/微信/Telegram）
- 自适应点击（通过模板定位按钮中心点击）
- 退出游戏时支持“结束游戏按钮”（实现预留接口）
- 运行录像（可选）
- 状态存储升级 sqlite
- GUI 配置界面（可选）

---

## 11. 里程碑计划（建议）

### Milestone 1：工程骨架 + 配置 + 日志 + 调度（0.5 天）

- config.toml
- logger/evidence
- scheduler + lock
- state.json 管理

### Milestone 2：游戏端识别与推进（1 天）

- anchors 制作
- wait_anchor + click 推进
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

## 12. 关键设计决策总结

- **状态识别优先使用锚点模板**（界面标题/固定图标区域），避免按钮 hover/亮度变化导致误判
- **动作采用固定坐标点击**（在分辨率固定情况下稳定且实现简单）
- **频道选择随机化**：前三个频道随机选一个，并记录选择结果便于回溯
- **退出策略 MVP 用 Alt+F4**，并预留“结束游戏”接口，方便后续改为更温和退出方式
- **每一步必须有 timeout + retry + evidence**，确保系统可恢复、可排查、不会卡死
- **账号池支持断点续跑**，降低长期运行维护成本
