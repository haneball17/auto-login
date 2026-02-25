# 同窗口键盘序列登录方案设计（主方案）

## 1. 文档目标

- 将“复制启动器登录 URL 到新浏览器会话”替换为“同窗口键盘序列登录”。
- 在不实现代码的前提下，明确可直接落地的设计边界、配置结构与验收标准。
- 作为后续实现与测试评审基线。

## 2. 需求审核（Code Prompt Coach）

### 2.1 清晰性

- 目标清晰：你已确认 `CDP attach` 不可用，要求采用同窗口键盘序列作为主方案。

### 2.2 具体性

- 关键现象明确：日志显示“网页登录成功后客户端未继续”，且人工在原浏览器登录可继续启动。
- 结论明确：问题是跨会话登录结果无法回传到启动器上下文。

### 2.3 上下文

- 项目现有流程、错误策略、证据留存机制已存在，可复用。
- 运行环境为 Windows 11，满足键鼠自动化前提。

### 2.4 结构与格式

- 本设计采用“状态机 + 配置驱动 + 分级回退”，确保后续实现可追踪、可测试、可回滚。

## 3. 现状与根因

### 3.1 当前流程（待替换部分）

- 启动器拉起登录浏览器。
- 脚本抓取登录 URL（进程命令行/地址栏剪贴板）。
- 在新的 Playwright headless 会话中登录。

### 3.2 根因判定

- 登录链路与启动器会话存在绑定（典型为 `state/端口/上下文`）。
- 新会话内“登录成功”不等于原会话回调成功，因此客户端不继续启动。

## 4. 设计目标与非目标

### 4.1 设计目标

- 主路径完全不依赖 URL 复制和新浏览器会话。
- 主路径不依赖图像匹配定位输入框。
- 支持失败留证、可重试、可回退到人工。
- 全部行为配置化，避免硬编码。

### 4.2 非目标

- 本阶段不引入窗口自动移动或尺寸调整（遵循现有规范）。
- 本阶段不实现 CDP / WebDriver 方案。
- 本文档不包含代码实现。

## 5. 总体方案

### 5.1 策略链（建议）

1. `in_window_keyboard`（主策略）
2. `manual_wait`（人工兜底）
3. `url_replay`（可选，默认建议关闭或降级为最后兜底）

### 5.2 核心思想

- 在启动器拉起的原浏览器窗口内，通过“焦点重置 + 键盘序列 + 粘贴输入 + 提交”完成登录。
- 图像/OCR仅用于状态判断（例如验证码、错误提示），不用于输入定位。

## 6. 状态机设计

### 6.1 状态定义

- `WAIT_BROWSER_WINDOW`：等待登录浏览器窗口出现。
- `PREPARE_FOCUS`：激活窗口并将焦点拉回网页主体。
- `RUN_SEQUENCE`：执行候选键盘序列（用户名、密码、提交）。
- `WAIT_RESULT`：等待游戏窗口出现或异常信号。
- `SUCCESS`：进入现有游戏流程。
- `FALLBACK_MANUAL`：转人工登录等待。
- `FAIL`：失败留证并触发既有错误策略。

### 6.2 状态转移

1. `WAIT_BROWSER_WINDOW` 超时 -> `FAIL`
2. `PREPARE_FOCUS` 失败 -> 重试序列；耗尽后 `FALLBACK_MANUAL`
3. `RUN_SEQUENCE` 单次失败 -> 下一个候选序列
4. `WAIT_RESULT` 发现游戏窗口 -> `SUCCESS`
5. `WAIT_RESULT` 命中验证码关键词 -> `FALLBACK_MANUAL`
6. 全序列失败且人工兜底关闭 -> `FAIL`

## 7. 键盘序列算法设计

### 7.1 焦点重置

1. 激活浏览器窗口（按 `browser_window_title_keyword` 选取最新激活窗口）。
2. 对窗口内部相对点执行一次点击（例如中心偏上，比例坐标）。
3. 执行固定次数 `Shift+Tab` 回卷，尽量回到表单起点。

### 7.2 输入与提交

1. 备份文本剪贴板内容。
2. 用户名输入：
- `Ctrl+A` 清空。
- 写入用户名到剪贴板并 `Ctrl+V`。
3. `Tab` 切换到密码框。
4. 密码输入：
- `Ctrl+A` 清空。
- 写入密码到剪贴板并 `Ctrl+V`。
5. 提交：
- 默认 `Enter`。
- 可配置为 `Tab` 后 `Enter` 或双 `Enter`。
6. 恢复文本剪贴板。

### 7.3 候选序列池（抗页面小改版）

- 通过 `tab_offsets` 配置多个偏移序列，例如 `[0, 1, 2]`。
- 每个偏移代表“回卷后额外按 `Tab` 的次数”。
- 逐个尝试，单次失败不立即终止整流程。

## 8. 配置设计（草案）

```yaml
web:
  login_strategies:
    - in_window_keyboard
    - manual_wait

  in_window_keyboard:
    enabled: true
    window_wait_timeout_seconds: 20
    action_timeout_seconds: 12
    submit_wait_timeout_seconds: 40
    max_attempts: 3
    pre_click_ratio_x: 0.50
    pre_click_ratio_y: 0.45
    focus_reset_shift_tab_count: 12
    tab_offsets: [0, 1, 2]
    key_interval_ms: 80
    clear_before_input: true
    submit_mode: enter
    captcha_keywords: ["验证码", "安全验证", "人机验证"]
    fail_keywords: ["错误", "失败", "重试", "账号或密码"]

  manual_wait:
    enabled: true
    timeout_seconds: 90
```

## 9. 模块改造设计（仅设计，不实现）

### 9.1 `src/config.py`

- 新增 `web.in_window_keyboard` 配置模型。
- 新增 `web.manual_wait` 配置模型。
- 新增 `web.login_strategies` 策略顺序配置与校验。

### 9.2 `src/web_login.py`

- 新增 `perform_web_login_in_window_keyboard(...)`。
- 新增 `wait_manual_login_success(...)`。
- 新增 `execute_login_strategies(...)` 统一调度。
- 保留 URL 回放逻辑作为可选兜底策略。

### 9.3 `src/runner.py`

- `run_launcher_web_login_flow(...)` 改为调用策略调度入口。
- 将“登录成功判定”统一收敛为“游戏窗口出现/流程进入后续场景”。

### 9.4 `src/evidence.py`（复用）

- 失败场景继续调用 `save_ui_evidence`。
- 通过 `extra.stage` 记录阶段，如 `in_window_keyboard/run_sequence_timeout`。

## 10. 异常处理与安全约束

- 所有等待必须带超时，禁止无限循环。
- 出现验证码关键词立即转人工兜底，不做盲重试。
- 剪贴板必须备份与恢复，仅处理文本剪贴板。
- 单账号失败不应中断全账号流程。

## 11. 观测与日志

- 关键日志字段：
- `strategy`：当前策略名
- `attempt`：第几次尝试
- `tab_offset`：当前序列偏移
- `result`：成功/失败/转人工
- `reason`：超时、关键词命中、窗口缺失等

## 12. 测试设计

### 12.1 Linux 可执行单元测试

- 配置模型校验测试（默认值、边界值、非法值）。
- 策略调度逻辑测试（主策略失败是否正确回退）。
- 超时与异常路径测试（确保失败留证调用触发）。

### 12.2 Windows 手工验证清单

1. 无验证码场景，连续 10 次登录成功率。
2. 页面小改版（Tab 顺序轻微变化）下，候选序列是否可自愈。
3. 验证码出现时是否稳定转人工。
4. 失败后证据目录是否完整（截图、OCR、错误信息）。

## 13. 验收标准

1. 不依赖 URL 回放即可完成登录并进入游戏流程。
2. 无验证码场景下，10 次连续运行成功率达到可接受阈值（建议 >= 90%）。
3. 所有失败路径都有证据输出。
4. 回退到人工后，人工登录成功可继续自动流程。

## 14. 风险与缓解

- 风险：Tab 顺序大改导致序列失效。
- 缓解：`tab_offsets` 扩展、日志标记、快速调参。

- 风险：登录页弹窗抢焦点。
- 缓解：增加焦点重置步骤与二次激活。

- 风险：验证码频率升高。
- 缓解：默认转人工，避免触发风控升级。

## 15. 待确认项（评审时确认）

1. `submit_mode` 默认采用 `enter` 是否符合当前登录页行为。
2. `tab_offsets` 初始值是否从 `[0, 1, 2]` 调整为更宽范围。
3. 是否保留 `url_replay` 作为最后兜底策略。
4. `manual_wait.timeout_seconds` 是否按账号池规模调大。
