# auto-login 自动登录改造方案

## 1. 文档目标

本文档用于指导 `auto-login` 项目从当前可运行的 MVP 自动化脚本，升级为更稳定、更安全、更易维护的 Windows 自动登录执行系统。

本次改造聚焦三条主链路：

- 网页自动登录链路
- Windows 桌面自动化链路
- 安全、可观测性与可维护性链路

文档目标不是单纯替换某个库，而是给出一套可以分阶段落地的工程方案。

## 2. 当前现状与问题

### 2.1 当前链路

当前项目大致流程如下：

1. 启动游戏启动器
2. 等待并点击启动按钮
3. 捕获 Edge 或登录页 URL
4. 使用 `Playwright` 无头网页登录
5. 等待游戏窗口出现
6. 使用 `OpenCV + OCR + pyautogui/win32` 执行频道选择、角色选择、进游戏与退出
7. 调度器按时间窗口执行多账号轮换

### 2.2 核心问题

#### A. 网页登录链路脆弱

当前登录主要依赖：

- 从浏览器进程命令行抓取登录 URL
- 必要时聚焦地址栏并读取剪贴板
- 依赖固定 selector 进行用户名密码填写和提交

存在的问题：

- 强依赖登录页当前 DOM 结构
- 每次都像“首次登录”一样处理，缺少认证态复用
- 无法优雅处理会话过期、风控、MFA、嵌入式浏览器等情况
- 出错时很难精准判断失败在哪一层

#### B. 桌面自动化过度依赖图像匹配

当前大量桌面操作依赖：

- 截图
- ROI 模板匹配
- OCR 识别
- 鼠标键盘模拟

存在的问题：

- 对分辨率、缩放、遮挡、主题变化敏感
- 启动器、浏览器、弹窗这类其实可以用 UI Automation 的界面，也走了视觉链路
- `pyautogui` 适合通用输入模拟，不适合作为稳定的 Windows UI 自动化主框架

#### C. 凭据与认证状态不安全

- 账号密码当前仍可直接存在 `config.yaml`
- 后续若加入 cookie、`storageState`、profile 目录，也容易继续明文存放
- 账号状态隔离、过期治理和日志脱敏还不够系统

#### D. 可观测性不足

虽然已有证据留存，但缺少统一的：

- 登录策略级别日志
- 网络级别证据
- 认证态来源说明
- Windows 控件级别证据
- 标准错误分类

#### E. 核心编排器过重

`runner.py` 已承担启动、登录、识别、点击、恢复、轮换等多种职责，后续继续叠加策略会越来越难维护。

## 3. 改造目标

### 3.1 业务目标

- 提升单账号登录成功率
- 提升多账号连续执行稳定性
- 降低对网页登录页结构变化的脆弱性
- 提升启动器和系统窗口操作稳定性
- 失败时能够快速定位根因

### 3.2 技术目标

- 登录链路从单路径升级为多策略
- 桌面控制从纯视觉驱动升级为 UIA + 视觉混合驱动
- 凭据和认证态本地安全存储
- 自动化证据具备可追溯性
- 模块职责分离，降低核心编排复杂度

### 3.3 约束条件

- 运行环境仍以 Windows 11 为主
- 优先采用开源或低持续成本方案
- 不依赖商业 SaaS 作为核心能力
- 不采用验证码绕过、反检测黑灰产方案
- 不将实验性 GUI Agent 直接用于生产主链路

## 4. 技术选型结论

### 4.1 网页自动登录主选：继续使用 Playwright

不建议将主引擎从 `Playwright` 切换到 `Selenium`、`browser-use` 或纯 RPA 平台。

原因：

- `Playwright` 原生支持 `storageState`
- 支持持久浏览器上下文
- 支持 `connect_over_cdp`
- 网络、trace、页面状态观测能力更强
- 与当前代码兼容性最高，迁移成本最低

### 4.2 Windows 桌面自动化主选：引入 pywinauto(UIA)

桌面控制建议改为双引擎：

- 启动器、浏览器、系统弹窗等非游戏窗口：`pywinauto + UI Automation`
- 游戏画面和 DirectX 区域：继续 `OpenCV + OCR + SendInput`

原因：

- UIA 更适合标准桌面控件
- 视觉方案仍然适合游戏画布
- 不建议让 `pyautogui + 图像匹配` 承担所有职责

### 4.3 OCR 与视觉链路

- 保留现有模板匹配主框架
- OCR 继续作为异常弹窗和兜底能力
- 可评估升级到 `PaddleOCR 3.x / PP-OCRv5`
- 暂不将 `OmniParser`、`UFO`、`browser-use` 等实验性 GUI/Agent 技术接入生产主流程

### 4.4 凭据安全

- 账号密码迁移到 Windows Credential Manager
- 本地敏感认证态使用 DPAPI 加密
- `storageState`、cookie、profile 元数据按账号隔离存储

## 5. 目标架构

改造后建议分为六层：

### 1. 调度与任务层

负责：

- 调度触发
- 账号轮换
- 停止控制
- 并发控制
- 重试策略

### 2. 流程编排层

负责：

- 单账号执行主流程
- 场景切换
- 策略选择
- 错误分流

### 3. 登录策略层

负责：

- 登录方式探测
- 认证态复用
- 浏览器接入
- 登录回退链

### 4. Windows 控制层

负责：

- UIA 控件操作
- 窗口查找与激活
- 焦点控制
- 弹窗处理

### 5. 视觉识别层

负责：

- 游戏画面模板匹配
- OCR 异常识别
- ROI 管理
- 多分辨率适配

### 6. 安全与观测层

负责：

- 凭据读取
- 认证态加密存储
- 统一日志
- 错误分类
- 证据输出

## 6. 网页自动登录改造方案

网页登录必须由单一路径改为分层策略，统一优先顺序如下：

1. 请求级登录
2. 持久 profile 复用
3. `storageState` 复用
4. CDP 附着现有浏览器 / WebView2
5. 表单自动填充登录
6. 人工初始化后复用

### 6.1 请求级登录

优先分析登录请求链路，确认是否存在：

- 标准登录 POST 接口
- token 交换接口
- 登录回调接口

如果能够直接完成 cookie 建立，则优先于 DOM 表单自动化。

### 6.2 持久 profile 复用

为每个账号维护独立浏览器 profile：

- 首次登录成功后保留真实上下文
- 后续优先验证并复用该上下文
- 失效时再回退到更重的登录方式

### 6.3 `storageState` 复用

对轻量站点优先使用 `storageState`：

- 登录成功后导出认证状态
- 后续执行前先导入
- 如果状态失效，则自动清理并降级

### 6.4 CDP / WebView2 接入

如果启动器实际使用 Chromium / Edge / WebView2：

- 优先研究 remote debugging 是否可开启
- 若可行，通过 `connect_over_cdp` 接入已有上下文
- 逐步替代当前“地址栏 + 剪贴板”获取 URL 的方案

### 6.5 表单自动填充降级为末级回退

保留现有表单登录能力，但不再作为唯一主路径。

需要加强：

- 登录页探测能力
- 登录成功判定能力
- 失败时的 DOM / screenshot / network 证据

## 7. WebAuthn / MFA / 新认证方式处理原则

### 7.1 WebAuthn / Passkeys

将其视为站点支持的正式认证方式，而不是自动化绕过技术。

适合方式：

- 人工首次绑定设备
- 后续配合持久 profile 复用设备态

### 7.2 MFA

对于短信、邮箱、多因子挑战：

- 目标不是“自动绕过”
- 正确方向是减少重新登录频率
- 优先依靠会话复用、可信设备和低风控策略

### 7.3 测试用途

虚拟 authenticator 只适合作为测试链路工具，不作为生产无人值守方案。

## 8. Windows 桌面自动化改造方案

### 8.1 双引擎原则

#### UIA 层负责

- 启动器窗口
- 浏览器窗口
- 系统消息框
- 标准输入框、按钮、列表

#### 视觉层负责

- 游戏画布
- 频道选择
- 角色选择
- 游戏内 HUD 或标题元素

### 8.2 控件定位优先级

统一采用以下优先级：

1. UI Automation selector
2. 控件属性组合定位
3. 句柄/父子树定位
4. 模板匹配
5. OCR 辅助
6. 坐标点击

禁止默认直接走坐标点击。

### 8.3 pywinauto 接入范围

第一阶段优先覆盖：

- 启动器窗口复用与激活
- 启动按钮识别与点击
- 浏览器窗口或标签页探测
- 常见确认/继续/错误弹窗处理

## 9. OCR 与视觉识别升级方案

### 9.1 OCR 路线

推荐路线：

- 保留 `cnocr` 兼容层
- 评估迁移到 `PaddleOCR 3.x / PP-OCRv5`

### 9.2 OCR 职责边界

OCR 只承担：

- 异常弹窗识别
- 公告/邮件/错误提示识别
- 低频兜底

OCR 不承担：

- 高频核心按钮定位
- 主场景切换判断

### 9.3 重型模型使用原则

只有在以下条件同时满足时，才考虑目标检测或 GUI parser：

- UIA 不可覆盖
- 模板匹配波动大
- OCR 也无法稳定判断
- 该区域属于核心主流程

## 10. 凭据与认证态安全方案

### 10.1 敏感信息范围

以下全部视为敏感信息：

- 账号密码
- cookie
- access token / refresh token
- `storageState`
- 浏览器 profile 元数据

### 10.2 账号密码存储

建议：

- `config.yaml` 不再保存明文密码
- 配置只保留账号标识和 credential key
- 执行时通过 Credential Manager 读取密码

### 10.3 会话状态存储

建议对以下内容按账号隔离存放并加密：

- `storageState`
- profile 元数据
- 登录策略缓存结果
- 失效原因
- 最后成功时间

### 10.4 日志脱敏

日志和证据中禁止输出：

- 明文密码
- 完整 cookie
- 完整 token
- 完整 `storageState`

## 11. 可观测性与故障诊断方案

### 11.1 统一错误分类

建议引入标准错误码：

- `SITE_UNREACHABLE`
- `LOGIN_URL_NOT_CAPTURED`
- `AUTH_STATE_EXPIRED`
- `LOGIN_FORM_CHANGED`
- `MFA_REQUIRED`
- `CAPTCHA_OR_RISK_CHALLENGE`
- `CDP_ATTACH_FAILED`
- `PROFILE_CORRUPTED`
- `WINDOW_NOT_FOUND`
- `UIA_ELEMENT_NOT_FOUND`
- `TEMPLATE_NOT_MATCHED`
- `OCR_EXCEPTION_DETECTED`
- `GAME_SCENE_TIMEOUT`
- `MANUAL_INTERVENTION_REQUIRED`

### 11.2 每次失败必须留存的证据

#### 浏览器侧

- 当前 URL
- 页面标题
- screenshot
- DOM 快照
- 最近网络摘要
- 本次使用的登录策略

#### 桌面侧

- 窗口标题和句柄
- 前后台状态
- UIA 控件树摘要
- ROI 截图
- 模板得分
- OCR 命中结果

## 12. 分阶段落地方案

### Phase 0：可行性验证

目标：

- 验证请求级登录是否可行
- 验证 WebView2 / CDP 是否可接入
- 验证 persistent profile 是否稳定
- 验证 pywinauto 对启动器的控件覆盖能力
- 对比 `cnocr` 与 `PaddleOCR` 在现有证据样本上的效果

### Phase 1：网页登录链路升级

目标：

- 登录由单路径升级为多策略
- 引入 `storageState` 和 persistent profile
- 完善登录策略回退和证据输出

### Phase 2：Windows UIA 主控接入

目标：

- 启动器、浏览器、系统弹窗尽量退出纯视觉路径
- UIA 成为默认主控层

### Phase 3：安全存储改造

目标：

- 移除明文密码
- 敏感认证态加密
- 日志脱敏

### Phase 4：可观测性与重构

目标：

- 统一错误码
- 标准化证据结构
- 将 `runner` 瘦身为流程编排层

## 13. 不做事项

本次改造明确不做：

- 验证码破解
- 第三方打码平台接入
- 反检测黑盒方案
- 将 GUI Agent / LLM 直接作为生产主控制链
- 为 Linux 环境强行补全 Windows UI 集成测试

## 14. 实施优先级

### P0

- 登录策略分层
- persistent profile / `storageState`
- 凭据脱离 `config.yaml`
- 登录失败分类与证据增强

### P1

- pywinauto 接入启动器/浏览器/弹窗
- WebView2/CDP 可行性落地
- OCR 升级评估与迁移

### P2

- `runner` 重构
- telemetry 统一化
- 账号冷却和质量统计

### P3

- 离线 UI 分析辅助工具
- 高级视觉模型辅助标注
- 实验性 GUI Agent 工具链调研

## 15. 结论

最合理的改造方向不是推翻现有 Python 栈，而是：

- 浏览器侧继续以 `Playwright` 为核心
- 登录侧从表单自动化升级为会话复用优先、多策略回退
- Windows 桌面侧引入 `pywinauto + UI Automation`
- 游戏视觉侧保留 `OpenCV + OCR`
- 安全侧引入 `Credential Manager + DPAPI`
- 运行侧补齐标准错误码、证据、trace 和状态治理

这条路线兼顾：

- 可落地性
- 改造收益
- 与现有代码兼容性
- 长期维护成本
- 低持续成本约束

## 16. 参考资料

- Playwright Authentication  
  https://playwright.dev/python/docs/auth
- Playwright `connect_over_cdp`  
  https://playwright.dev/python/docs/api/class-browsertype
- Playwright WebView2  
  https://playwright.dev/python/docs/webview2
- Playwright APIRequestContext  
  https://playwright.dev/python/docs/api/class-apirequestcontext
- Selenium BiDi  
  https://www.selenium.dev/documentation/webdriver/bidi/w3c/
- Selenium CDP  
  https://www.selenium.dev/documentation/webdriver/bidi/cdp/
- MDN Web Authentication API  
  https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API
- MDN Passkeys  
  https://developer.mozilla.org/en-US/docs/Web/Security/Authentication/Passkeys
- Chrome DevTools WebAuthn  
  https://developer.chrome.com/docs/devtools/webauthn/
- Microsoft UI Automation Overview  
  https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview
- pywinauto Getting Started  
  https://pywinauto.readthedocs.io/en/latest/getting_started.html
- Power Automate Desktop UI Elements  
  https://learn.microsoft.com/en-us/power-automate/desktop-flows/ui-elements
- WebView2 Remote Debugging  
  https://learn.microsoft.com/en-us/microsoft-edge/webview2/how-to/remote-debugging-desktop
- WinAppDriver  
  https://github.com/microsoft/WinAppDriver
- Appium Windows Driver  
  https://github.com/appium/appium-windows-driver
- browser-use  
  https://github.com/browser-use/browser-use
- OmniParser  
  https://github.com/microsoft/OmniParser
- UFO  
  https://github.com/microsoft/UFO
- Windows DPAPI  
  https://learn.microsoft.com/en-us/windows/win32/api/dpapi/
- Windows Credential / Authentication Functions  
  https://learn.microsoft.com/en-us/windows/win32/secauthn/authentication-functions
