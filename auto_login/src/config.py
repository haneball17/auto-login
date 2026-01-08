from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # 仅用于兼容旧版本
    try:
        import tomli as tomllib
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "当前 Python 版本缺少 tomllib，且未安装 tomli，"
            "请先安装依赖：pip install tomli"
        ) from exc


class ConfigError(Exception):
    """配置校验失败异常。"""

    def __init__(self, errors: Sequence[str]) -> None:
        message = "配置校验失败：\n- " + "\n- ".join(errors)
        super().__init__(message)
        self.errors = list(errors)


@dataclass(frozen=True)
class ValidationConfig:
    """校验策略配置。"""

    strict_paths: bool


@dataclass(frozen=True)
class LoggingConfig:
    """日志配置。"""

    dir: Path
    level: str


@dataclass(frozen=True)
class EvidenceConfig:
    """证据留存配置。"""

    dir: Path


@dataclass(frozen=True)
class ScheduleConfig:
    """调度配置。"""

    times: list[str]
    min_gap_minutes: int


@dataclass(frozen=True)
class LauncherConfig:
    """启动器配置。"""

    exe_path: str
    game_process_name: str
    game_window_title_keyword: str


@dataclass(frozen=True)
class WebConfig:
    """网页登录配置。"""

    login_url: str
    username_selector: str
    password_selector: str
    login_button_selector: str
    success_selector: str


@dataclass(frozen=True)
class Account:
    """账号对象。"""

    username: str
    password: str


@dataclass(frozen=True)
class AccountsConfig:
    """账号池配置。"""

    pool: list[Account]


@dataclass(frozen=True)
class FlowConfig:
    """流程配置。"""

    step_timeout_seconds: int
    click_retry: int
    template_threshold: float
    enter_game_wait_seconds: int
    channel_random_range: int


@dataclass(frozen=True)
class WindowConfig:
    """窗口配置。"""

    x: int
    y: int
    w: int
    h: int
    dpi_scale_required: int


@dataclass(frozen=True)
class AnchorsConfig:
    """界面锚点配置。"""

    channel_title: Path
    role_title: Path
    in_game_right_icons: Path


@dataclass(frozen=True)
class AppConfig:
    """配置对象，保留原始配置与配置文件路径，便于后续追踪。"""

    raw: dict[str, Any]
    config_path: Path
    app_name: str
    validation: ValidationConfig
    logging: LoggingConfig
    evidence: EvidenceConfig
    schedule: ScheduleConfig
    launcher: LauncherConfig
    web: WebConfig
    accounts: AccountsConfig
    flow: FlowConfig
    window: WindowConfig
    anchors: AnchorsConfig


def _ensure_mapping(data: Any) -> dict[str, Any]:
    """确保 TOML 解析结果为字典结构，避免非预期类型导致崩溃。"""

    if isinstance(data, Mapping):
        return dict(data)
    raise ValueError("配置内容必须为表结构（TOML 顶层为键值表）")


def _resolve_path(config_path: Path, value: str | Path) -> Path:
    """将相对路径解析为绝对路径，基准为配置文件所在目录。"""

    candidate = Path(str(value))
    if candidate.is_absolute():
        return candidate
    return (config_path.parent / candidate).resolve()


def _get_section(raw: dict[str, Any], name: str, errors: list[str]) -> dict[str, Any]:
    """获取配置分组，确保为字典结构。"""

    value = raw.get(name)
    if value is None:
        errors.append(f"缺少配置分组：[{name}]")
        return {}
    if not isinstance(value, Mapping):
        errors.append(f"配置分组 [{name}] 必须为键值表")
        return {}
    return dict(value)


def _get_str(
    section: Mapping[str, Any],
    key: str,
    errors: list[str],
    *,
    allow_empty: bool = False,
) -> str:
    """读取字符串字段，必要时记录错误。"""

    value = section.get(key)
    if not isinstance(value, str):
        errors.append(f"字段 {key} 必须为字符串")
        return ""
    cleaned = value.strip()
    if not cleaned and not allow_empty:
        errors.append(f"字段 {key} 不能为空")
    return cleaned


def _get_int(
    section: Mapping[str, Any],
    key: str,
    errors: list[str],
    *,
    min_value: int | None = None,
) -> int:
    """读取整数字段，必要时记录错误。"""

    value = section.get(key)
    if not isinstance(value, int):
        errors.append(f"字段 {key} 必须为整数")
        return 0
    if min_value is not None and value < min_value:
        errors.append(f"字段 {key} 不能小于 {min_value}")
    return value


def _get_float(
    section: Mapping[str, Any],
    key: str,
    errors: list[str],
    *,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    """读取浮点数字段，必要时记录错误。"""

    value = section.get(key)
    if not isinstance(value, (int, float)):
        errors.append(f"字段 {key} 必须为数字")
        return 0.0
    number = float(value)
    if min_value is not None and number < min_value:
        errors.append(f"字段 {key} 不能小于 {min_value}")
    if max_value is not None and number > max_value:
        errors.append(f"字段 {key} 不能大于 {max_value}")
    return number


def _parse_times(times: list[str], min_gap: int, errors: list[str]) -> None:
    """校验运行时间格式与最小间隔。"""

    if len(times) != 2:
        errors.append("schedule.times 必须包含 2 个时间点")
        return

    def to_minutes(value: str) -> int | None:
        try:
            parsed = datetime.strptime(value, "%H:%M")
        except ValueError:
            return None
        return parsed.hour * 60 + parsed.minute

    parsed_times = [to_minutes(value) for value in times]
    if any(value is None for value in parsed_times):
        errors.append("schedule.times 必须符合 HH:MM 格式")
        return

    t0, t1 = parsed_times
    diff = abs(t1 - t0)
    gap = min(diff, 24 * 60 - diff)
    if gap < min_gap:
        errors.append(
            f"两次运行间隔不足 {min_gap} 分钟，当前为 {gap} 分钟"
        )


def _validate_log_level(level: str, errors: list[str]) -> None:
    """校验日志级别是否合法。"""

    allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if level not in allowed:
        errors.append(f"logging.level 必须为 {sorted(allowed)} 之一")


def _parse_accounts(
    section: Mapping[str, Any], errors: list[str]
) -> AccountsConfig:
    """解析账号池配置。"""

    raw_pool = section.get("pool")
    if not isinstance(raw_pool, list):
        errors.append("accounts.pool 必须为数组")
        return AccountsConfig(pool=[])

    pool: list[Account] = []
    for index, item in enumerate(raw_pool):
        if not isinstance(item, Mapping):
            errors.append(f"accounts.pool[{index}] 必须为对象")
            continue
        username = _get_str(item, "username", errors)
        password = _get_str(item, "password", errors)
        if username and password:
            pool.append(Account(username=username, password=password))

    if not pool:
        errors.append("accounts.pool 不能为空")
    return AccountsConfig(pool=pool)


def load_config(config_path: Path) -> AppConfig:
    """加载配置文件并返回配置对象，失败时抛出明确异常。"""

    config_path = config_path.expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    if not config_path.is_file():
        raise FileNotFoundError(f"配置路径不是文件：{config_path}")

    with config_path.open("rb") as file_handle:
        data = tomllib.load(file_handle)

    raw = _ensure_mapping(data)
    errors: list[str] = []

    app_cfg = _get_section(raw, "app", errors)
    validation_cfg = _get_section(raw, "validation", errors)
    logging_cfg = _get_section(raw, "logging", errors)
    evidence_cfg = _get_section(raw, "evidence", errors)
    schedule_cfg = _get_section(raw, "schedule", errors)
    launcher_cfg = _get_section(raw, "launcher", errors)
    web_cfg = _get_section(raw, "web", errors)
    accounts_cfg = _get_section(raw, "accounts", errors)
    flow_cfg = _get_section(raw, "flow", errors)
    window_cfg = _get_section(raw, "window", errors)
    anchors_cfg = _get_section(raw, "anchors", errors)

    app_name = _get_str(app_cfg, "name", errors)
    strict_paths = validation_cfg.get("strict_paths", False)
    if not isinstance(strict_paths, bool):
        errors.append("validation.strict_paths 必须为布尔值")
        strict_paths = False

    log_dir_value = _get_str(logging_cfg, "dir", errors)
    log_level_value = _get_str(logging_cfg, "level", errors)
    _validate_log_level(log_level_value.upper(), errors)
    log_dir = _resolve_path(config_path, log_dir_value)
    logging = LoggingConfig(dir=log_dir, level=log_level_value.upper())

    evidence_dir_value = _get_str(evidence_cfg, "dir", errors)
    evidence_dir = _resolve_path(config_path, evidence_dir_value)
    evidence = EvidenceConfig(dir=evidence_dir)

    times = schedule_cfg.get("times")
    if not isinstance(times, list) or not all(isinstance(item, str) for item in times):
        errors.append("schedule.times 必须为字符串数组")
        times = []
    min_gap_minutes = _get_int(
        schedule_cfg, "min_gap_minutes", errors, min_value=1
    )
    if times:
        _parse_times([item.strip() for item in times], min_gap_minutes, errors)
    schedule = ScheduleConfig(
        times=[item.strip() for item in times],
        min_gap_minutes=min_gap_minutes,
    )

    launcher = LauncherConfig(
        exe_path=_get_str(launcher_cfg, "exe_path", errors),
        game_process_name=_get_str(launcher_cfg, "game_process_name", errors),
        game_window_title_keyword=_get_str(
            launcher_cfg, "game_window_title_keyword", errors
        ),
    )

    web = WebConfig(
        login_url=_get_str(web_cfg, "login_url", errors),
        username_selector=_get_str(web_cfg, "username_selector", errors),
        password_selector=_get_str(web_cfg, "password_selector", errors),
        login_button_selector=_get_str(web_cfg, "login_button_selector", errors),
        success_selector=_get_str(web_cfg, "success_selector", errors),
    )

    accounts = _parse_accounts(accounts_cfg, errors)

    flow = FlowConfig(
        step_timeout_seconds=_get_int(
            flow_cfg, "step_timeout_seconds", errors, min_value=1
        ),
        click_retry=_get_int(flow_cfg, "click_retry", errors, min_value=0),
        template_threshold=_get_float(
            flow_cfg, "template_threshold", errors, min_value=0.0, max_value=1.0
        ),
        enter_game_wait_seconds=_get_int(
            flow_cfg, "enter_game_wait_seconds", errors, min_value=0
        ),
        channel_random_range=_get_int(
            flow_cfg, "channel_random_range", errors, min_value=1
        ),
    )

    window = WindowConfig(
        x=_get_int(window_cfg, "x", errors),
        y=_get_int(window_cfg, "y", errors),
        w=_get_int(window_cfg, "w", errors, min_value=1),
        h=_get_int(window_cfg, "h", errors, min_value=1),
        dpi_scale_required=_get_int(
            window_cfg, "dpi_scale_required", errors, min_value=1
        ),
    )

    anchors = AnchorsConfig(
        channel_title=_resolve_path(
            config_path, _get_str(anchors_cfg, "channel_title", errors)
        ),
        role_title=_resolve_path(
            config_path, _get_str(anchors_cfg, "role_title", errors)
        ),
        in_game_right_icons=_resolve_path(
            config_path,
            _get_str(anchors_cfg, "in_game_right_icons", errors),
        ),
    )

    validation = ValidationConfig(strict_paths=strict_paths)

    if strict_paths:
        if launcher.exe_path and not Path(launcher.exe_path).exists():
            errors.append(f"launcher.exe_path 不存在：{launcher.exe_path}")
        if not anchors.channel_title.exists():
            errors.append(f"anchors.channel_title 不存在：{anchors.channel_title}")
        if not anchors.role_title.exists():
            errors.append(f"anchors.role_title 不存在：{anchors.role_title}")
        if not anchors.in_game_right_icons.exists():
            errors.append(
                f"anchors.in_game_right_icons 不存在：{anchors.in_game_right_icons}"
            )

    if errors:
        raise ConfigError(errors)

    return AppConfig(
        raw=raw,
        config_path=config_path,
        app_name=app_name,
        validation=validation,
        logging=logging,
        evidence=evidence,
        schedule=schedule,
        launcher=launcher,
        web=web,
        accounts=accounts,
        flow=flow,
        window=window,
        anchors=anchors,
    )


def get_logging_settings(config: AppConfig) -> tuple[Path, str]:
    """读取日志配置并返回日志目录与日志级别。"""

    return config.logging.dir, config.logging.level


def get_evidence_dir(config: AppConfig) -> Path:
    """读取证据留存目录。"""

    return config.evidence.dir
