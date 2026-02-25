# 窗口离屏修复方案（可直接实施版）

## 1. 范围与约束

### 1.1 本次范围

- 仅修复“游戏窗口部分/全部离屏时流程直接失败并重启”的问题。
- 保持当前网页登录方案不变（不执行 `web-login-in-window-keyboard-design.md`）。
- 保持现有账号循环、失败留证、调度策略不变。

### 1.2 约束

- 平台仍以 Windows 11 为唯一运行环境。
- 所有新参数必须配置化，禁止硬编码。
- 所有等待逻辑必须有超时，禁止死循环。

## 2. 当前行为与根因（基于现代码）

### 2.1 当前行为

- 运行中会在多个关键步骤调用窗口可见性检查 `src/runner.py:_ensure_window_visibility`。
- 当可见比例低于阈值时，直接 `raise RuntimeError`（通过 `_handle_step_failure`）。
- 账号级异常捕获后，若 `flow.error_policy=restart`，执行 `_force_exit_game` 杀进程并重试。

### 2.2 根因

- 已有“检测”，缺少“自愈”。
- 离屏不是致命业务错误，但当前与致命错误走同一失败路径，导致直接重启。

## 3. 改造目标（本次固定决策）

1. 离屏场景优先执行“自动复位”，复位失败后再走既有失败策略。
2. 自动复位默认仅作用于游戏窗口，避免影响启动器和浏览器窗口。
3. 自动复位第一版只“移动窗口”，不调整窗口尺寸。
4. 保留当前 `error_policy` 作为最终兜底行为。

## 4. 方案总览

### 4.1 核心流程

`可见性检查 -> 低于阈值 -> 尝试复位(最多N次) -> 复验比例 -> 成功继续 / 失败再报错`

### 4.2 复位动作

1. 获取目标窗口 `hwnd` 与窗口矩形。
2. 读取虚拟桌面矩形。
3. 计算“可视区域内的目标左上角”（带 `padding`）。
4. 调用 `SetWindowPos` 移动窗口到目标位置。
5. 等待短暂冷却时间后复验可见比例。

### 4.3 失败处理

- 若复位后仍低于阈值，按现有失败路径处理：
- `error_policy=restart`：账号级清理时会杀进程重试。
- `error_policy=manual`：进入人工介入。

## 5. 配置变更（可直接落地）

在 `flow` 下新增以下字段：

```yaml
flow:
  # 已有
  window_visibility_check_enabled: true
  window_visible_ratio_min: 0.85

  # 新增
  window_auto_recover_enabled: true
  window_auto_recover_targets:
    - game
  window_auto_recover_max_attempts: 2
  window_auto_recover_cooldown_seconds: 0.5
  window_auto_recover_padding_px: 24
  window_auto_recover_allow_resize: false
```

字段定义：

- `window_auto_recover_enabled`: 是否启用离屏自动复位。
- `window_auto_recover_targets`: 允许复位的窗口类型，第一版仅支持 `game`。
- `window_auto_recover_max_attempts`: 单次检查最大复位次数，建议 `1~3`。
- `window_auto_recover_cooldown_seconds`: 每次移动后等待时间。
- `window_auto_recover_padding_px`: 窗口与可视边界的最小留白。
- `window_auto_recover_allow_resize`: 是否允许复位时缩放窗口，第一版固定 `false`。

## 6. 代码改造清单（模块级）

### 6.1 `src/config.py`

改动点：

1. `FlowConfig` 新增上述 6 个字段及默认值。
2. 增加校验：
- `window_auto_recover_max_attempts >= 1`
- `window_auto_recover_cooldown_seconds >= 0`
- `window_auto_recover_padding_px >= 0`
3. 保持向后兼容：未配置新字段时使用默认值。

### 6.2 `src/process_ops.py`

新增窗口复位函数（建议）：

1. `_get_window_rect_by_hwnd(hwnd) -> (x, y, w, h)`
2. `_clamp_window_origin_to_visible(window_rect, virtual_rect, padding) -> (x, y)`
3. `recover_window_to_visible(title_keyword, padding_px, allow_resize) -> dict`

返回建议：

```text
{
  "success": bool,
  "hwnd": int | None,
  "before_rect": tuple | None,
  "after_rect": tuple | None,
  "virtual_rect": tuple | None,
  "reason": str
}
```

### 6.3 `src/runner.py`

改动点：

1. 扩展 `_ensure_window_visibility(...)`：
- 在比例不足时先尝试自动复位。
- 每次复位后重新读取窗口矩形并复验比例。
- 复位成功直接返回，不抛错。
- 复位失败才调用 `_handle_step_failure`。
2. 增加日志字段：
- `visible_ratio_before`
- `visible_ratio_after`
- `recover_attempt`
- `window_rect_before/after`

### 6.4 `config.yaml`

在 `flow` 段补充新配置默认值，便于直接运行与调参。

### 6.5 `docs/window-offscreen-fix-plan.md`

本文档作为实施基线，后续实现需与本文保持一致。

## 7. 详细执行步骤（实施顺序）

1. **配置层**  
在 `src/config.py` 和 `config.yaml` 增加字段与校验，并补齐配置单测。

2. **窗口操作层**  
在 `src/process_ops.py` 增加复位能力函数，确保纯函数部分可单测。

3. **流程层接入**  
在 `src/runner.py:_ensure_window_visibility` 集成复位逻辑。

4. **日志与证据**  
统一补充复位相关结构化日志；复位失败仍走现有证据留存。

5. **回归测试**  
执行 Linux 单测 + Windows 手工回归验证。

## 8. 测试计划

### 8.1 Linux 单元测试（必须）

文件建议：

- `tests/test_config.py`
- `tests/test_runner_lifecycle.py`
- `tests/test_ui_ops.py`（若新增几何函数在 ui_ops）

新增用例：

1. 新配置默认值与非法值校验。
2. 可见性不足且复位成功时，不触发失败异常。
3. 可见性不足且复位失败时，触发失败异常。
4. 复位仅对 `game` 目标生效。

### 8.2 Windows 手工验证（必须）

场景：

1. 游戏窗口左侧离屏（部分离屏）。
2. 游戏窗口完全移出可视区域（全部离屏）。
3. 多显示器负坐标场景。
4. 正常可见场景回归（不应劣化）。

通过标准：

- 离屏时优先自动复位，复位成功后流程继续推进。
- 不再出现“首次离屏即杀进程重试”。

## 9. 验收标准

1. 离屏场景下，单次检测至少尝试一次自动复位。
2. 复位成功后，同一流程可继续执行模板识别与点击。
3. 复位失败才进入原失败链路（重启或人工）。
4. 正常场景成功率与当前版本相比不下降。

## 10. 风险与对策

### 10.1 风险：多同名窗口误选

- 对策：复位函数记录 `hwnd`，复位前后基于同一 `hwnd` 校验。

### 10.2 风险：窗口尺寸大于可视区域，比例无法达到阈值

- 对策：第一版不缩放，失败后走原策略；后续再评估 `allow_resize=true`。

### 10.3 风险：频繁复位导致抖动

- 对策：限制 `max_attempts`，并设置 `cooldown_seconds`。

## 11. 回滚策略

1. 将 `flow.window_auto_recover_enabled` 设为 `false`，即可回退为当前行为。
2. 保留现有失败链路，不改业务主流程，确保可快速回滚。
3. 以小步提交实施，按提交粒度回退。

## 12. 实施完成定义（DoD）

1. 文档中配置项全部在 `src/config.py` 与 `config.yaml` 实装。
2. 新增与修改单测全部通过。
3. Windows 手工验证四个场景记录完成。
4. 日志可定位每次复位动作与结果。
