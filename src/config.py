from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config.yaml")
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_ANCHOR_FILES = [
    "channel_select/title.png",
    "channel_select/roi.json",
    "character_select/title.png",
    "character_select/roi.json",
    "character_select/character_1.png",
    "in_game/name_cecilia.png",
    "in_game/title_duel.png",
    "in_game/roi.json",
    "launcher_start_enabled/button.png",
]
DEFAULT_EXCEPTION_KEYWORDS = [
    "信息失败",
    "失败",
    "错误",
    "重试",
    "提示",
    "邮件",
    "邮箱",
    "公告",
]
DEFAULT_CLICKABLE_KEYWORDS = [
    "确认",
    "确定",
    "OK",
    "好的",
    "是",
    "继续",
]
DEFAULT_CLICK_CANDIDATES = [
    (0, 0),
    (0, -8),
    (0, 8),
    (-8, 0),
    (8, 0),
]
DEFAULT_CLICK_BACKOFF_MS = [100, 250, 500]


def _parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%H:%M")


def _minutes_gap(a: str, b: str) -> int:
    time_a = _parse_time(a)
    time_b = _parse_time(b)
    minutes_a = time_a.hour * 60 + time_a.minute
    minutes_b = time_b.hour * 60 + time_b.minute
    diff = abs(minutes_a - minutes_b)
    return min(diff, 24 * 60 - diff)


def _deep_merge(base: dict, override: dict) -> dict:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            isinstance(value, dict)
            and isinstance(result.get(key), dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class RandomWindow(BaseModel):
    center: str
    jitter_minutes: int = 0

    @field_validator("center")
    @classmethod
    def _validate_center(cls, value: str) -> str:
        _parse_time(value)
        return value

    @field_validator("jitter_minutes")
    @classmethod
    def _validate_jitter(cls, value: int) -> int:
        if value < 0:
            raise ValueError("jitter_minutes 必须为非负整数")
        return value


class ScheduleConfig(BaseModel):
    mode: Literal["random_window", "fixed_times"] = "random_window"
    min_gap_minutes: int = 90
    random_windows: list[RandomWindow] = Field(default_factory=list)
    fixed_times: list[str] = Field(default_factory=list)

    @field_validator("min_gap_minutes")
    @classmethod
    def _validate_min_gap(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("min_gap_minutes 必须大于 0")
        return value

    @model_validator(mode="after")
    def _validate_schedule(self) -> "ScheduleConfig":
        if self.mode == "random_window":
            if len(self.random_windows) != 2:
                raise ValueError("random_windows 需要正好两个时间窗口")
            gap = _minutes_gap(
                self.random_windows[0].center,
                self.random_windows[1].center,
            )
            if gap < self.min_gap_minutes:
                raise ValueError("随机窗口中心时间间隔小于最小间隔")
        else:
            if len(self.fixed_times) != 2:
                raise ValueError("fixed_times 需要正好两个时间点")
            for value in self.fixed_times:
                _parse_time(value)
            gap = _minutes_gap(self.fixed_times[0], self.fixed_times[1])
            if gap < self.min_gap_minutes:
                raise ValueError("固定时间间隔小于最小间隔")
        return self


class LauncherConfig(BaseModel):
    exe_path: Path | None = None
    launcher_process_name: str | None = None
    lifecycle_mode: Literal["clean", "reuse"] = "reuse"
    game_process_name: str
    game_window_title_keyword: str
    launcher_window_title_keyword: str
    start_button_roi_path: Path | None = None
    start_button_roi_name: str = "button"
    start_button_threshold: float = 0.86
    start_button_color_rule_enabled: bool = False
    start_button_color_min_blue: int = 120
    start_button_color_dominance: int = 20

    @field_validator("start_button_threshold")
    @classmethod
    def _validate_start_button_threshold(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("start_button_threshold 必须在 0~1 之间")
        return value

    @field_validator("start_button_color_min_blue", "start_button_color_dominance")
    @classmethod
    def _validate_color_rule(cls, value: int) -> int:
        if value < 0:
            raise ValueError("颜色阈值不能小于 0")
        return value


class LauncherEnvConfig(BaseModel):
    exe_path: Path | None = None
    launcher_process_name: str | None = None
    lifecycle_mode: Literal["clean", "reuse"] | None = None
    game_process_name: str | None = None
    game_window_title_keyword: str | None = None
    launcher_window_title_keyword: str | None = None
    start_button_roi_path: Path | None = None
    start_button_roi_name: str | None = None
    start_button_threshold: float | None = None
    start_button_color_rule_enabled: bool | None = None
    start_button_color_min_blue: int | None = None
    start_button_color_dominance: int | None = None


class WebConfig(BaseModel):
    login_url: str
    username_selector: str
    password_selector: str
    login_button_selector: str
    success_selector: str
    browser_process_name: str = "msedge.exe"
    browser_window_title_keyword: str = "猪咪启动器"
    close_browser_on_url_capture: bool = True


class AccountItem(BaseModel):
    username: str
    password: str
    enabled: bool = True
    group: str | None = None


class AccountsConfig(BaseModel):
    pool: list[AccountItem] = Field(min_length=1)


class FlowConfig(BaseModel):
    step_timeout_seconds: int = 120
    login_url_timeout_seconds: int = 15
    web_login_timeout_seconds: int = 30
    start_button_timeout_seconds: int = 60
    start_button_click_retry: int = 3
    start_button_click_verify_seconds: int = 5
    click_retry: int = 3
    template_threshold: float = 0.86
    enter_game_wait_seconds: int = 60
    enter_game_wait_seconds_random_range: int = 15
    wait_next_account_seconds: int = 10
    ocr_interval_seconds: int = 10
    ocr_region_ratio: float = 0.6
    ocr_keywords: list[str] = Field(default_factory=list)
    exception_keywords: list[str] = Field(default_factory=list)
    channel_exception_keywords: list[str] = Field(default_factory=list)
    clickable_keywords: list[str] = Field(
        default_factory=lambda: list(DEFAULT_CLICKABLE_KEYWORDS),
    )
    channel_clickable_keywords: list[str] = Field(default_factory=list)
    ocr_keyword_min_score: float = 0.5
    ocr_failure_policy: Literal["fallback", "ignore", "fail"] = "fallback"
    template_exception_rounds: int = 2
    template_fallback_delay_seconds: int = 10
    channel_exception_delay_seconds: int = 20
    error_policy: Literal["restart", "manual"] = "restart"
    channel_random_range: int = 3
    channel_search_timeout_seconds: int = 5
    channel_refresh_max_retry: int = 3
    channel_refresh_delay_ms: int = 5000
    channel_startgame_retry: int = 3
    in_game_match_timeout_seconds: int = 7
    in_game_name_threshold: float = 0.6
    in_game_title_threshold: float = 0.86
    window_visibility_check_enabled: bool = True
    window_visible_ratio_min: float = 0.85
    window_auto_recover_enabled: bool = True
    window_auto_recover_targets: list[
        Literal["game", "launcher", "browser"]
    ] = Field(default_factory=lambda: ["game"])
    window_auto_recover_max_attempts: int = 2
    window_auto_recover_cooldown_seconds: float = 0.5
    window_auto_recover_padding_px: int = 24
    window_auto_recover_allow_resize: bool = False
    click_strategy_enabled: bool = True
    click_verify_foreground_enabled: bool = True
    click_foreground_wait_ms: int = 120
    click_candidates: list[tuple[int, int]] = Field(
        default_factory=lambda: list(DEFAULT_CLICK_CANDIDATES)
    )
    click_max_attempts: int = 3
    click_backoff_ms: list[int] = Field(
        default_factory=lambda: list(DEFAULT_CLICK_BACKOFF_MS)
    )
    click_post_check_delay_ms: int = 120
    click_point_guard_padding_px: int = 6
    click_ocr_fallback_enabled: bool = True
    force_kill_on_exit_fail: bool = True
    account_max_retry: int = 2

    @field_validator(
        "step_timeout_seconds",
        "login_url_timeout_seconds",
        "web_login_timeout_seconds",
        "start_button_timeout_seconds",
        "start_button_click_retry",
        "click_retry",
        "enter_game_wait_seconds",
        "channel_search_timeout_seconds",
        "channel_refresh_max_retry",
        "channel_refresh_delay_ms",
        "channel_startgame_retry",
        "in_game_match_timeout_seconds",
        "template_exception_rounds",
        "window_auto_recover_max_attempts",
        "click_max_attempts",
    )
    @classmethod
    def _validate_positive_int(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("数值必须大于 0")
        return value

    @field_validator(
        "start_button_click_verify_seconds",
        "enter_game_wait_seconds_random_range",
        "wait_next_account_seconds",
        "ocr_interval_seconds",
        "template_fallback_delay_seconds",
        "channel_exception_delay_seconds",
        "window_auto_recover_padding_px",
        "click_foreground_wait_ms",
        "click_post_check_delay_ms",
        "click_point_guard_padding_px",
    )
    @classmethod
    def _validate_non_negative_int(cls, value: int) -> int:
        if value < 0:
            raise ValueError("数值不能小于 0")
        return value

    @field_validator("ocr_region_ratio")
    @classmethod
    def _validate_ratio(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("ocr_region_ratio 必须在 0~1 之间")
        return value

    @field_validator("template_threshold")
    @classmethod
    def _validate_threshold(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("template_threshold 必须在 0~1 之间")
        return value

    @field_validator("in_game_name_threshold", "in_game_title_threshold")
    @classmethod
    def _validate_in_game_threshold(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("in_game_threshold 必须在 0~1 之间")
        return value

    @field_validator("window_visible_ratio_min")
    @classmethod
    def _validate_window_visible_ratio(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("window_visible_ratio_min 必须在 0~1 之间")
        return value

    @field_validator("ocr_keyword_min_score")
    @classmethod
    def _validate_ocr_score(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("ocr_keyword_min_score 必须在 0~1 之间")
        return value

    @field_validator("window_auto_recover_cooldown_seconds")
    @classmethod
    def _validate_recover_cooldown(cls, value: float) -> float:
        if value < 0:
            raise ValueError(
                "window_auto_recover_cooldown_seconds 不能小于 0"
            )
        return value

    @field_validator(
        "exception_keywords",
        "channel_exception_keywords",
        "clickable_keywords",
        "channel_clickable_keywords",
        "ocr_keywords",
    )
    @classmethod
    def _validate_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned

    @field_validator("window_auto_recover_targets")
    @classmethod
    def _validate_recover_targets(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("window_auto_recover_targets 不能为空")
        deduped: list[str] = []
        for item in value:
            key = str(item).strip()
            if not key:
                continue
            if key not in deduped:
                deduped.append(key)
        if not deduped:
            raise ValueError("window_auto_recover_targets 不能为空")
        return deduped

    @field_validator("click_candidates")
    @classmethod
    def _validate_click_candidates(
        cls,
        value: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        if not value:
            raise ValueError("click_candidates 不能为空")

        normalized: list[tuple[int, int]] = []
        for item in value:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError("click_candidates 每项必须是长度为 2 的坐标")
            normalized.append((int(item[0]), int(item[1])))
        return normalized

    @field_validator("click_backoff_ms")
    @classmethod
    def _validate_click_backoff_ms(cls, value: list[int]) -> list[int]:
        if not value:
            raise ValueError("click_backoff_ms 不能为空")
        normalized: list[int] = []
        for item in value:
            number = int(item)
            if number < 0:
                raise ValueError("click_backoff_ms 不能包含负数")
            normalized.append(number)
        return normalized

    @model_validator(mode="after")
    def _normalize_keywords(self) -> "FlowConfig":
        fields_set = self.model_fields_set
        if "exception_keywords" not in fields_set:
            if self.ocr_keywords:
                self.exception_keywords = list(self.ocr_keywords)
            else:
                self.exception_keywords = list(DEFAULT_EXCEPTION_KEYWORDS)
        if "channel_exception_keywords" not in fields_set:
            self.channel_exception_keywords = list(self.exception_keywords)
        if "channel_clickable_keywords" not in fields_set:
            self.channel_clickable_keywords = list(self.clickable_keywords)
        return self

    @field_validator("channel_random_range", "account_max_retry")
    @classmethod
    def _validate_range(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("数值必须大于 0")
        return value


class WindowConfig(BaseModel):
    x: int = 0
    y: int = 0
    width: int = 1920
    height: int = 1440
    dpi_scale_percent: int = 150

    @field_validator("width", "height", "dpi_scale_percent")
    @classmethod
    def _validate_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("数值必须大于 0")
        return value


class EvidenceConfig(BaseModel):
    dir: Path = Path("evidence")
    retention_days: int = 7

    @field_validator("retention_days")
    @classmethod
    def _validate_retention(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("retention_days 必须大于 0")
        return value


class AppConfig(BaseModel):
    schedule: ScheduleConfig
    launcher: LauncherConfig
    web: WebConfig
    accounts: AccountsConfig
    flow: FlowConfig
    window: WindowConfig
    evidence: EvidenceConfig


class EnvSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(DEFAULT_ENV_PATH),
        env_nested_delimiter="__",
        extra="ignore",
    )

    schedule: ScheduleConfig | None = None
    launcher: LauncherEnvConfig | None = None
    web: WebConfig | None = None
    accounts: AccountsConfig | None = None
    flow: FlowConfig | None = None
    window: WindowConfig | None = None
    evidence: EvidenceConfig | None = None


def load_config(
    config_path: Path | str = DEFAULT_CONFIG_PATH,
    env_path: Path | str = DEFAULT_ENV_PATH,
    base_dir: Path | None = None,
    validate_paths: bool = True,
    required_anchors: list[str] | None = None,
) -> AppConfig:
    config_path = Path(config_path)
    env_path = Path(env_path)
    base_dir = base_dir or Path.cwd()

    if not config_path.is_file():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

    env_settings = EnvSettings(
        _env_file=str(env_path) if env_path.is_file() else None,
    )
    merged = _deep_merge(data, env_settings.model_dump(exclude_none=True))

    try:
        config = AppConfig.model_validate(merged)
    except ValidationError as exc:
        raise ValueError(f"配置校验失败: {exc}") from exc

    config = _resolve_paths(config, base_dir)
    if validate_paths:
        _validate_paths(config, base_dir, required_anchors)

    return config


def _resolve_paths(config: AppConfig, base_dir: Path) -> AppConfig:
    launcher_path = None
    if config.launcher.exe_path is not None:
        launcher_path = _resolve_path(base_dir, config.launcher.exe_path)
    launcher_process_name = config.launcher.launcher_process_name
    if not launcher_process_name and launcher_path is not None:
        launcher_process_name = launcher_path.name
    start_button_roi_path = None
    if config.launcher.start_button_roi_path is not None:
        start_button_roi_path = _resolve_path(
            base_dir,
            config.launcher.start_button_roi_path,
        )
    evidence_dir = _resolve_path(base_dir, config.evidence.dir)

    launcher = config.launcher.model_copy(
        update={
            "exe_path": launcher_path,
            "launcher_process_name": launcher_process_name,
            "start_button_roi_path": start_button_roi_path,
        }
    )
    evidence = config.evidence.model_copy(update={"dir": evidence_dir})

    return config.model_copy(update={"launcher": launcher, "evidence": evidence})


def _resolve_path(base_dir: Path, path: Path) -> Path:
    return path if path.is_absolute() else base_dir / path


def _validate_paths(
    config: AppConfig,
    base_dir: Path,
    required_anchors: list[str] | None = None,
) -> None:
    exe_path = config.launcher.exe_path
    if exe_path is None:
        raise ValueError(
            "启动器路径为空，请在 config.yaml 或 .env 设置 "
            "launcher.exe_path / LAUNCHER__EXE_PATH"
        )
    if not exe_path.is_file():
        raise ValueError(f"启动器路径不存在: {exe_path}")

    if config.launcher.start_button_roi_path is not None:
        roi_path = config.launcher.start_button_roi_path
        if not roi_path.is_file():
            raise ValueError(f"ROI 文件不存在: {roi_path}")
        anchors_dir = (base_dir / "anchors").resolve()
        try:
            roi_path.resolve().relative_to(anchors_dir)
        except ValueError as exc:
            raise ValueError("ROI 文件必须位于 anchors/ 目录") from exc

    anchors_dir = base_dir / "anchors"
    anchor_files = (
        DEFAULT_ANCHOR_FILES
        if required_anchors is None
        else required_anchors
    )
    missing = [
        name
        for name in anchor_files
        if not (anchors_dir / name).is_file()
    ]
    if missing:
        raise ValueError(f"缺少锚点文件: {', '.join(missing)}")
