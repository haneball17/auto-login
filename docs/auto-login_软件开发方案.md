# Windows11 游戏自动登录与签到自动化项目（MVP）软件开发方案

> 目标：在 Windows11 环境下使用 Python 开发一个自动化项目，支持**每日两次登录周期**（间隔≥1.5小时）、支持**账号池轮换**、支持**网页登录**、支持**游戏客户端自动操作**（频道选择→角色选择→进入游戏→等待30秒→退出），并具备完善的日志、错误处理与证据留存能力。
> 备注：本项目属于游戏自动化行为，可能违反游戏服务条款，有封号风险，请自行评估。

***

## 1. 需求分析与验证

### 1.1 背景与业务目标

你需要在游戏中每日上线签到（在线时长1个半小时拿满奖励），每次登录流程包含：

1. 启动登录器 EXE
2. 等待登录器“启动”按钮可用（由灰转蓝）
3. 点击启动按钮（roi.json 中 button 的中心点）
4. EXE 拉起网页登录页
5. 输入账号密码点击登录
6. 等待游戏客户端启动并加载至频道选择界面
7. 在频道选择界面选择频道进入角色选择界面
8. 选择角色进入游戏界面
9. 等待30秒退出游戏
10. 完成一次账号的“登录周期”

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

***

## 2. 技术路线选择

### 2.1 推荐总体方案（MVP）

✅**Playwright（网页登录） + OpenCV（模板匹配识别界面） + PyAutoGUI（鼠标键盘动作） + APScheduler（调度） + psutil/win32（进程与窗口管理）**

**选择理由：**

- 登录页无验证码/二次验证，且 HTML 已知，可通过稳定 selector 自动登录（ `#u` , `#p` , `#btn` ）

- 游戏 UI 分辨率可能变化（默认 1920×1440，可配置），采用**多分辨率模板优先 + 默认模板回退**进行识别

- 窗口模式可固定窗口位置/大小，使坐标点击稳定

- 全 Python 技术栈，便于工程化开发与部署

- 可实现完善日志、错误处理与证据留存

***

## 3. 轻量架构设计（Architecture）

### 3.1 简化结构

项目分为两块，避免过度抽象：

1. **调度与流程（runner）** - 读取配置、生成随机或固定执行时间、执行账号轮换与流程推进、失败重试
2. **执行与支撑（ops）** - Web 登录、界面识别与点击、进程与窗口控制、日志与证据留存

***

## 4. 模块设计与职责拆分（精简版）

以“少文件、少抽象、函数直观”为目标，尽量合并模块。

建议目录结构如下（MVP，精简，根目录直接放置）：

```python
.
├─ pyproject.toml
├─ poetry.lock
├─ README.md
├─ config.yaml
├─ .env
├─ anchors/
│  ├─ 1920x1440/            # 可选：分辨率模板（存在则优先使用）
│  ├─ 960x720/              # 可选：分辨率模板（存在则优先使用）
│  ├─ channel_select/
│  │  ├─ title.png
│  │  ├─ channel_1.png
│  │  └─ roi.json
│  ├─ character_select/
│  │  ├─ title.png
│  │  ├─ character_1.png
│  │  └─ roi.json
│  ├─ in_game/
│  │  ├─ name_cecilia.png
│  │  ├─ title_duel.png
│  │  └─ roi.json
│  └─ launcher_start_enabled/
│     ├─ button.png
│     ├─ roi.json
│     └─ full.png
├─ ref/
│  └─ web_login/
│     └─登录 · 猪咪云启动器.html
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

- web\_login.py：自动捕获登录 URL（Edge 命令行）+ Playwright headless 登录与成功判定，失败证据留存

- ui\_ops.py：窗口定位、截图、模板匹配、点击/热键，含启动器按钮可用检测（运行时按窗口截图 + roi.json 相对坐标裁剪，按钮可用后点击中心点；游戏内点击优先使用 SendInput）

- process\_ops.py：启动器启动、进程等待、强制结束

- evidence.py：截图/HTML/堆栈留存，保留 7 天并定期清理

- logger.py：日志初始化与统一格式，日志按日期分割保存到 logs/YYYY-MM-DD.log

- ui.py：PyQt6 前端入口（配置编辑、执行控制、状态/日志查看）

实现原则（精简风格）：

- 以函数为主，尽量扁平化，避免不必要的类与层级

- 仅在代码变复杂时再拆分文件

***

## 5. 关键流程设计（状态机推进）

### 5.1 界面状态锚点（anchors）

只用锚点判断“当前在哪个界面”，不依赖按钮模板：

- 默认模板放在 `anchors/<场景>/...`
- 若检测到窗口分辨率为 `宽x高` 且存在 `anchors/<宽>x<高>/`，则优先使用该分辨率模板
- 若分辨率模板缺失，则**记录报错并回退默认模板**（不中断流程）

- **频道选择界面** ： `anchors/channel_select/title.png` （裁剪“选择频道”）

- **频道模板与按钮** ：`anchors/channel_select/channel_1.png ~ channel_N.png`，`anchors/channel_select/roi.json` 内包含 `channel_region/button_startgame/button_refresh/button_endgame`

- **角色选择界面** ： `anchors/character_select/title.png` （裁剪“选择角色”）

- **进入游戏界面** ： `anchors/in_game/name_cecilia.png` 与 `anchors/in_game/title_duel.png` 联合匹配（ROI 使用 `anchors/in_game/roi.json`）

- **启动器按钮可用** ： `anchors/launcher_start_enabled/button.png`（蓝色“启动”按钮模板）

- 需要在对应分辨率与 DPI 下重新截取锚点图片

启动器按钮检测设计（方案 A）：

- 通过窗口标题定位启动器窗口（从配置 `launcher_window_title_keyword` 读取，默认“猪咪启动器”）

- 截取当前窗口图像，再按 `roi.json` 的相对坐标裁剪 ROI

- ROI 内执行模板匹配（蓝色按钮模板），不使用颜色阈值

- 匹配成功后点击 ROI 的中心点

- 存在多个匹配窗口时，选择最新激活窗口

- 若启动器窗口已存在，直接激活复用，不强制重启

ROI 资源格式规范（以 `anchors/launcher_start_enabled` 为例）：

- `full.png`：完整截图

- `roi.json`：包含 `rois` 数组，元素含 `name/x/y/w/h/dpi_scale`

- `name` 对应同名截图文件（例如 `name=button` 对应 `button.png`）

- `ref/` 用于存放参考资料（HTML 等），运行时不引用

- 用于 ROI 匹配的模板文件放在 `anchors/<场景>/` 下，文件夹名称表示场景

- 运行时不直接使用 `roi.json` 中的 `window.rect`，而是先定位当前窗口再截图裁剪，避免窗口位置变化造成偏移

### 5.2 频道随机选择策略

在频道选择界面：

- 频道选择分为两阶段：先检测 `title.png` 出现，再在 `channel_region` 内识别可点击频道

- 在 `channel_region` 内匹配 `channel_1~channel_N` 模板，统计可点击频道数量后随机选择一个

- 选中频道后等待 500ms，再点击 `button_startgame` 进入角色选择界面

- 若超时仍未发现任何频道，点击 `button_refresh` 刷新；刷新次数超过阈值则点击 `button_endgame` 结束流程

- 若点击 `button_startgame` 后未进入角色选择界面，回退到频道选择重试，超过阈值视为失败

- 点击 `button_endgame` 后若进程未退出，则根据 `force_kill_on_exit_fail` 强制杀进程

- 频道/按钮 ROI 在同一分辨率下固定；`channel_region` 为放大区域，无需模板

- 若 `channel_random_range` 超过现有 `channel_*` 模板数量，直接报错提示配置修正

随机选择应具备“确定性可复现”能力（日志记录随机种子或选择结果）：

- 日志：记录选择了第几个频道（1/2/3）

### 5.3 角色选择与进入游戏策略

角色界面：

- 先匹配 `title.png` 确认角色选择界面出现

- 在 `character_region` 内匹配 `character_1.png` 定位角色位置，单击选中后等待 1s

- 单击 `button_startgame` 进入游戏

- 进入游戏判定：`name_cecilia`（`in_game_name_threshold`）与 `title_duel`（`in_game_title_threshold`）同时匹配，ROI 使用 `anchors/in_game/roi.json`

- 若匹配 in_game 超时（`in_game_match_timeout_seconds`），回退到角色选择重试（`channel_startgame_retry`）

- 重试失败则点击 `button_endgame` 结束流程，若进程未退出则强制结束

- 成功进入游戏后等待 `enter_game_wait_seconds ± enter_game_wait_seconds_random_range` 的随机时长，随后强制退出

### 5.4 Web 登录策略（启动器 → 登录页）

- 启动按钮点击后，从 `web.browser_process_name` 对应的浏览器进程命令行中解析登录 URL（包含 `port/state`）
- 若命令行未拿到 URL，按 `web.browser_window_title_keyword` 过滤 Edge 窗口，短暂聚焦地址栏并通过剪贴板读取作为兜底（只恢复文本剪贴板）
- 若超时仍未捕获到登录 URL，直接报错（不使用固定 URL 兜底）
- 使用 Playwright **headless** 打开捕获到的 URL
- 通过配置选择器填写账号/密码，点击登录
- 以 `success_selector` 判定成功后，立即关闭 Playwright；捕获 URL 后关闭登录页标签（Ctrl+W），避免影响其他 Edge 窗口

***

## 6. 可靠性设计（日志、超时、重试、恢复）

### 6.1 超时与重试矩阵（建议默认值）

优先使用统一默认值，关键步骤再单独覆盖。

| Step        | 超时   | 重试 | 失败处理                       |
| ----------- | ---- | -- | -------------------------- |
| 启动 launcher | 30s  | 2  | 记录失败，跳过该账号                 |
| 等待启动按钮可用    | 60s  | 2  | 保存截图，重启 launcher           |
| Web 登录      | 60s  | 2  | 保存 HTML + 截图，尝试重启 launcher |
| 等游戏进程       | 120s | 2  | 强制结束残留进程后重试                |
| 等频道界面       | 120s | 2  | 保存截图，尝试回到上一阶段或重启           |
| 选频道/开始      | 20s  | 2  | 保存截图，重新点击                  |
| 等角色界面       | 120s | 2  | 保存截图，重启账号流程                |
| 选角色/开始      | 20s  | 2  | 保存截图，重新点击                  |
| 等进入游戏       | 120s | 2  | 保存截图，重启账号流程                |
| 游戏内等待       | 60s±15s | 0  | -                          |
| 退出游戏        | 20s  | 2  | 若失败则强制结束进程                 |

> 目标：任何一步都不能无限等待，必须可退出与可继续。

### 6.2 故障隔离策略

- 单个账号失败不会导致整个 cycle 崩溃

- cycle 结束后输出 summary

- 对失败账号进行记录并在下一次周期继续尝试（可配置）

- 单账号失败最大重试 2 次（可配置）

- 失败步骤重试从“启动 launcher”阶段重新开始

- 单账号流程结束后等待 `wait_next_account_seconds` 再进入下一个账号

### 6.3 防重入/防并发

- Scheduler 触发时加锁（文件锁或进程锁）

- 若锁被占用则跳过本次或延迟（可配置）

- 运行锁文件路径：`logs/run.lock`

***

## 7. 配置设计（config.yaml）

配置包含：

- schedule：调度策略（固定时间或随机窗口）、最小间隔

- accounts：账号池

- launcher：启动器路径、进程名、窗口标题关键字

- web：登录 URL（用于参考/调试）、选择器、成功判定 selector、浏览器进程名、窗口标题关键字、捕获后是否关闭浏览器窗口

- flow：超时/重试/模板阈值/随机策略/退出策略/账号最大重试

- window：位置与尺寸、分辨率与 DPI（仅用于校验）

- evidence：保存路径与保留天数

使用 pydantic-settings 从 .env 覆盖同名字段（默认规则，嵌套字段使用 `__`）。

调度生成策略：

- 程序启动时生成当天两次执行时间

- 若某个时间已过，立即补跑一次

示例字段（概念级）：

```yaml
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
  launcher_window_title_keyword: "猪咪启动器"
  start_button_roi_path: "anchors/launcher_start_enabled/roi.json"
  start_button_roi_name: "button"

web:
  login_url: "https://nas.nekous.cn:7005/launcher-login.html"
  username_selector: "#u"
  password_selector: "#p"
  login_button_selector: "#btn"
  success_selector: "#msg.uika-msg.ok"
  browser_process_name: "msedge.exe"
  browser_window_title_keyword: "登录 · 猪咪云启动器"
  close_browser_on_url_capture: true

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
  enter_game_wait_seconds: 60
  enter_game_wait_seconds_random_range: 15
  wait_next_account_seconds: 10
  channel_random_range: 3
  channel_search_timeout_seconds: 5
  channel_refresh_max_retry: 3
  channel_refresh_delay_ms: 5000
  channel_startgame_retry: 3
  in_game_match_timeout_seconds: 7
  in_game_name_threshold: 0.6
  in_game_title_threshold: 0.86
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

***

## 8. 前端设计（PyQt6）

目标：仅覆盖“基础设置 + 执行控制 + 状态/日志浏览”，避免复杂交互。

### 8.1 界面结构

- 主窗口：QMainWindow + QTabWidget

- 设置页：原始 YAML 编辑器（QPlainTextEdit），支持“加载/保存/语法校验提示”，仅编辑 config.yaml；提供调度设置表单（两次执行时间、最小间隔、随机范围）

- 执行页：显示调度进程状态、当前账号、当前步骤；提供“开始/停止/强制停止/立即执行一次”按钮

- 日志页：日志文件选择（按日期）、关键词过滤、实时滚动、打开文件夹（logs/evidence 下拉选择）

### 8.2 行为约定（简化）

- 开始：若 runner 未运行，则启动 `python -m src.main`

- 停止：写入 stop.flag，runner 在安全点检测后优雅退出

- 优雅停止策略：完成当前账号流程后退出

- 强制停止：若仍在运行，直接结束进程

- 立即执行一次（单次全账号）：调用 `python -m src.main --once`（M3 完成后）

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

- 在角色界面执行 wait\_anchor(character)

- 在游戏内执行 wait\_anchor(in\_game)

### 9.3 E2E 测试（完整链路）

- 使用测试账号跑完整流程

- 检查日志完整性

- 检查 evidence 输出

- 确认退出后进程不存在

***

## 10. 部署与运行

### 10.1 MVP 运行方式

- 采用常驻方式运行： `python -m src.main`（由 APScheduler 负责调度）

- 如需系统任务计划，仅用于拉起常驻进程，不承担调度逻辑

- 依赖管理使用 Poetry（pyproject.toml）

- 启动前端： `python -m src.ui`（M5 完成后）

- 单次全账号执行：`python -m src.main --once`

- 注意：必须在有桌面会话的用户环境运行（UI 自动化依赖桌面）

### 10.2 环境约束

必须满足：

- 分辨率与 DPI 与配置保持一致（默认 1920×1440、150%，可配置）

- 游戏窗口固定位置/大小（配置化，允许变化）

- 运行期间避免用户操作鼠标键盘（降低误操作）

- 实际运行仅支持 Windows11（Linux 仅保证测试可运行）

***

## 11. 可扩展规划（非 MVP）

后续可加入：

- 失败通知（邮件/微信/Telegram）

- 自适应点击（通过模板定位按钮中心点击）

- 退出游戏时支持“结束游戏按钮”（实现预留接口）

- 运行录像（可选）

- 状态存储升级 sqlite

- GUI 配置界面（可选）

***

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

> 预计 2\~3 天可完成 MVP。

***

## 13. 关键设计决策总结

- **状态识别优先使用锚点模板** （界面标题/固定图标区域），避免按钮 hover/亮度变化导致误判

- **动作采用固定坐标点击** （在当前分辨率下稳定且实现简单）

- **频道选择随机化** ：前三个频道随机选一个，并记录选择结果便于回溯

- **调度策略**：默认 07:00±3 分钟、13:00±3 分钟随机执行，同时支持固定时间模式

- **配置方案**：config.yaml + pydantic-settings + .env（默认规则）

- **实现风格**：优先简单清晰的函数结构，避免不必要的复杂抽象

- **退出策略**：优先 Alt+F4，失败时强制结束进程，不计划短期内实现“结束游戏”按钮

- **账号重试**：单账号失败最大重试 2 次（可配置）

- **步骤重试**：每个失败步骤重试 2 次，且从启动器阶段重新开始

- **每一步必须有 timeout + retry + evidence** ，确保系统可恢复、可排查、不会卡死

- **账号池支持断点续跑** ，降低长期运行维护成本
