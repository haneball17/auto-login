# AGENTS.md

## 项目上下文 (Context)
这是一个基于 **Windows 11** 环境的 **游戏自动登录与签到自动化项目 (MVP)**。
目标是实现每日两次（间隔≥1.5小时）的自动登录周期，支持账号池轮换、网页登录、游戏客户端操作（频道/角色选择）及自动退出。

## 技术栈 (Tech Stack)
- **语言**: Python 3.x
- **包管理**: Poetry (必须使用 `poetry add/install`)
- **核心库**:
  - `playwright`: 用于网页端登录 (无需验证码时)。
  - `opencv-python`: 用于游戏界面状态识别 (模板匹配)。
  - `pyautogui`: 用于模拟鼠标键盘操作。
  - `apscheduler`: 用于任务调度 (随机/固定时间)。
  - `pyqt6`: 用于简单的配置与日志查看 GUI。
  - `pydantic-settings`: 用于配置管理。

## 目录结构与职责 (Project Structure)
项目结构应保持扁平，避免过度抽象。
- `config.yaml`: 用户配置文件 (调度、账号、路径)。
- `src/`: 源代码目录
  - `runner.py`: 核心调度器 (Runner)，负责账号轮换、流程推进、失败重试。
  - `web_login.py`: 捕获 Edge 登录 URL + Playwright headless 网页登录。
  - `ui_ops.py`: 负责屏幕截图、模板匹配 (OpenCV)、模拟点击。
  - `process_ops.py`: 负责游戏进程启动 (`subprocess`) 与强制结束 (`psutil`)。
  - `evidence.py`: 负责失败时的证据留存 (截图/HTML)。
  - `state.py`: 读写 `data/state.json`，记录账号执行状态。
- `anchors/`: 存放用于模板匹配的界面截图，按场景分目录 (如 `anchors/channel_select/title.png`)。
- `ref/`: 存放参考资料文件（HTML 等），运行时不引用。
- `evidence/`: 存放运行时的错误截图和日志。

## 开发规范 (Development Guidelines)

### 1. 架构原则
- **函数式优先**: 尽量使用函数而非复杂的类层级，保持代码直观。
- **配置驱动**: 所有可变参数（重试次数、超时时间、路径）必须从 `config.yaml` 读取，禁止硬编码。
- **环境约束**: 仅支持 Windows 11。Linux 环境仅用于运行非 GUI 相关的单元测试。
- **代码风格**: 遵循 PEP 8 代码风格规范。
- **窗口配置**: window 配置仅用于校验，不做自动移动/调整。

### 2. 错误处理与证据留存 (Critical)
- **拒绝死循环**: 任何 `while` 循环或等待步骤必须包含 `timeout`。
- **失败留证**: 任何步骤失败（如超时、未找到元素），**必须**调用 `evidence.py` 保存当前屏幕截图、网页 HTML 或错误堆栈。
- **故障隔离**: 单个账号失败不应导致程序崩溃，应记录错误后跳过，继续执行下一个账号。

### 3. 自动化策略细节
  - **网页登录**: 优先从 `web.browser_process_name` 进程命令行获取登录 URL；失败时按 `web.browser_window_title_keyword` 过滤 Edge 窗口，短暂聚焦地址栏并通过剪贴板读取（仅恢复文本剪贴板）；捕获 URL 后关闭登录页 Edge 窗口；使用 Playwright headless 的 Selector (`#u`, `#p`) 定位，不要使用坐标。
- **游戏操作**:
  - **状态识别**: 使用 `anchors/<场景>/` 下的图片进行 OpenCV 模板匹配，判断当前处于哪个界面。
  - **ROI 资源格式**: `anchors/<场景>/full.png` 为全图，`roi.json` 含 `rois` 数组，`name` 对应 `name.png` 截图。
  - **ROI 使用方式**: 运行时先定位窗口，再截取窗口图像并按 ROI 相对坐标裁剪，避免窗口移动造成偏移。
  - **点击操作**: 在确认界面后，使用固定坐标或相对坐标点击 (MVP阶段)。
  - **启动器按钮**: 仅使用蓝色按钮模板匹配，匹配成功后点击 ROI 中心点。
  - **窗口选择**: 存在多个匹配窗口时，选择最新激活窗口。
  - **窗口复用**: 启动器窗口已存在时直接激活复用。
  - **退出策略**: 优先模拟 `Alt+F4`。如果失败，使用 `psutil` 强制杀进程。
  - **优雅停止**: 收到 stop.flag 后，完成当前账号流程再退出。

## 常用命令 (Commands)
- **安装依赖**: `poetry install`
- **运行主程序**: `poetry run python -m src.main` (常驻进程，由 Scheduler 调度)
- **运行 GUI**: `poetry run python -m src.ui`（M5 完成后）
- **测试**: `poetry run pytest` (注意：GUI/E2E 测试需在有显示器的 Windows 环境下运行)

## 提交前检查 (Pre-commit)
- 确保 `config.yaml` 结构符合 `config.py` 中的 Pydantic 定义。
- 检查 `logs/` 和 `evidence/` 目录下的生成文件是否符合预期。
