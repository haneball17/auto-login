# 点击可靠性增强方案（不新增锚点版）

## 1. 文档目标

- 在不新增锚点图、不新增第三方依赖的前提下，提升自动流程点击成功率。
- 将点击能力从“分散调用”升级为“统一可复用模块”。
- 保持现有主流程状态机不变，仅增强点击执行链路与验证闭环。

## 2. 需求审核（Code Prompt Coach）

### 2.1 清晰性

- 目标明确：提升点击稳定性，尤其是任务栏遮挡、窗口焦点丢失、点击落空等问题。

### 2.2 具体性

- 已明确 10+ 条改进项，覆盖点击前、点击中、点击后、失败兜底与日志观测。

### 2.3 上下文

- 项目已有 `ui_ops.py`、`runner.py`、`ocr_ops.py`、窗口复位能力，可直接复用。

### 2.4 结构与格式

- 本方案采用“模块化封装 + 配置驱动 + 渐进替换”的落地方式，可直接实施。

## 3. 固定设计决策

1. 新增可复用模块 `src/click_ops.py`，集中实现强化点击能力。
2. `runner.py` 只保留业务流程编排，不再内嵌复杂点击细节。
3. 点击执行必须支持“前置校验 -> 候选点点击 -> 结果确认 -> 失败兜底”闭环。
4. 所有阈值、退避、偏移、超时都进入 `config.yaml`（配置驱动）。

## 4. 范围与非范围

### 4.1 实施范围

- 强化点击基础能力：
  - 激活窗口与前台确认
  - 点击点工作区可见性检查（避开任务栏）
  - 多点容错点击（中心 + 偏移）
  - 退避重试
  - SendInput 失败兜底增强
  - 点击后短时二次确认
  - 细粒度日志记录
- 复用现有锚点的闭环验证：
  - 场景切换验证
  - 闭环失败后重试
  - OCR 关键词兜底点击

### 4.2 非范围

- 不新增锚点图。
- 不改网页登录链路。
- 不改调度策略和账号轮换策略。

## 5. 总体架构

## 5.1 新模块职责：`src/click_ops.py`

- 输入：窗口标题、ROI 信息/坐标点、点击策略配置、可选闭环验证回调。
- 输出：结构化结果（是否成功、尝试次数、命中偏移、失败原因、观测信息）。

建议接口：

```python
def click_with_strategy(...) -> ClickResult: ...
def click_roi_with_strategy(...) -> ClickResult: ...
```

数据结构建议：

```python
@dataclass(frozen=True)
class ClickAttemptResult:
    success: bool
    point: tuple[int, int]
    offset_index: int
    reason: str

@dataclass(frozen=True)
class ClickResult:
    success: bool
    attempts: list[ClickAttemptResult]
    final_reason: str
```

## 5.2 业务层接入方式：`src/runner.py`

- 启动器点击、频道按钮、角色按钮统一改为调用 `click_ops`。
- 业务层只传入：
  - 当前点击目标（窗口 + ROI）
  - 点击后验证函数（是否进入下一场景）
  - 当前阶段标识（用于日志和证据）

## 6. 详细执行链路

1. 前置激活  
- 激活目标窗口并确认前台窗口标题匹配。

2. 点击点计算  
- ROI 中心点作为主点。
- 生成偏移候选点（中心、上、下、左、右）。

3. 可见性校验  
- 基于工作区（不含任务栏）校验点位可点击。
- 不可点击则触发窗口复位并重算点位。

4. 候选点击执行  
- 顺序尝试候选点。
- 每次点击后做短等待与二次确认。

5. 闭环验证  
- 调用业务回调（模板/场景/OCR）判断动作是否生效。
- 失败后进入退避重试。

6. OCR 兜底（可配置）  
- 连续失败后触发 `确认/继续/OK` 关键词点击。

7. 最终失败处理  
- 输出结构化失败原因并交由现有 `_handle_step_failure` 留证。

## 7. 配置设计（草案）

在 `flow` 下新增：

```yaml
flow:
  click_strategy_enabled: true
  click_verify_foreground_enabled: true
  click_foreground_wait_ms: 120

  click_candidates:
    - [0, 0]
    - [0, -8]
    - [0, 8]
    - [-8, 0]
    - [8, 0]

  click_max_attempts: 3
  click_backoff_ms:
    - 100
    - 250
    - 500

  click_post_check_delay_ms: 120
  click_point_guard_padding_px: 6

  click_sendinput_fallback_enabled: true
  click_ocr_fallback_enabled: true
```

字段说明：

- `click_candidates`: 候选偏移点集合（相对中心点）。
- `click_backoff_ms`: 每轮失败后的退避间隔。
- `click_point_guard_padding_px`: 点击点距工作区边界的安全边距。
- `click_ocr_fallback_enabled`: 是否启用 OCR 关键词兜底点击。

## 8. 模块改造清单

1. `src/click_ops.py`（新增）
- 封装强化点击核心逻辑。

2. `src/config.py`
- 增加点击策略相关配置模型与校验。

3. `config.yaml`
- 增加默认点击策略参数。

4. `src/runner.py`
- 将关键按钮点击改为 `click_ops` 调用。
- 注入“点击后闭环验证”回调。

5. `src/ui_ops.py`
- 复用现有底层点击能力；必要时补充分步兜底函数（不改变外部接口）。

6. `tests/test_click_ops.py`（新增）
- 覆盖候选点、退避、可见性校验、复位触发、闭环分支。

7. `tests/test_runner_lifecycle.py`
- 覆盖 runner 与 click_ops 接入后的关键流程。

## 9. 实施顺序（建议）

1. 配置层（`config.py` + `config.yaml` + 配置单测）
2. 新增 `click_ops.py`，先完成纯逻辑与结构化结果
3. 替换启动器按钮点击链路
4. 替换 `_click_roi_button` 链路
5. 接入闭环验证与 OCR 兜底
6. 完整回归测试

## 10. 测试计划

### 10.1 Linux 可执行单测

- 配置合法性与默认值测试。
- 点击候选点顺序与退避间隔测试。
- 点位不可见时复位触发测试。
- 闭环成功/失败分支测试。

### 10.2 Windows 手工验证

1. 任务栏遮挡底部按钮场景。
2. 窗口靠边导致点位越界场景。
3. 前台被抢焦点场景。
4. 正常场景回归（成功率不降低）。

## 11. 验收标准

1. 任务栏遮挡时不再盲点任务栏。
2. 关键点击步骤成功率明显提升（建议统计重试次数和成功率）。
3. 闭环失败才重试，避免无效点击循环。
4. 失败日志可直接定位“失败在哪个偏移点、哪次尝试、前台窗口是谁”。

## 12. 风险与对策

1. 风险：重试过多拖慢流程  
- 对策：严格限制 `click_max_attempts`，退避可配置。

2. 风险：OCR 兜底误点  
- 对策：仅在闭环失败后触发，且关键词与分数阈值可控。

3. 风险：不同机器分辨率差异  
- 对策：偏移与边距参数配置化，按环境调优。

## 13. 回滚策略

1. 配置开关 `click_strategy_enabled=false` 回退到原点击路径。
2. 保留旧调用入口一段过渡期，便于快速切换。
3. 分阶段提交，按模块粒度回滚。

## 14. 实施完成定义（DoD）

1. 强化点击能力已封装到独立模块并在关键流程复用。
2. 所有新增参数配置化并完成校验。
3. 单测通过，Windows 关键场景验证通过。
4. 日志可完整还原每次点击尝试过程。
