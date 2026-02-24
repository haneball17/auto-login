from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.config import DEFAULT_ANCHOR_FILES, FlowConfig, load_config


def _write_config(
    path: Path,
    exe_path: Path | None,
    roi_path: Path,
    lifecycle_mode: str | None = None,
) -> None:
    lines = [
        "schedule:",
        "  mode: \"random_window\"",
        "  min_gap_minutes: 90",
        "  random_windows:",
        "    - center: \"07:00\"",
        "      jitter_minutes: 3",
        "    - center: \"13:00\"",
        "      jitter_minutes: 3",
        "  fixed_times:",
        "    - \"07:00\"",
        "    - \"13:00\"",
        "",
        "launcher:",
    ]
    if exe_path is not None:
        lines.append(f"  exe_path: \"{exe_path.as_posix()}\"")
    if lifecycle_mode is not None:
        lines.append(f"  lifecycle_mode: \"{lifecycle_mode}\"")
    lines.extend(
        [
            "  game_process_name: \"DNF Taiwan\"",
            "  game_window_title_keyword: \"DNF Taiwan\"",
            "  launcher_window_title_keyword: \"Launcher\"",
            f"  start_button_roi_path: \"{roi_path.as_posix()}\"",
            "  start_button_roi_name: \"button\"",
            "",
            "web:",
            "  login_url: \"https://example.com/login\"",
            "  username_selector: \"#u\"",
            "  password_selector: \"#p\"",
            "  login_button_selector: \"#btn\"",
            "  success_selector: \"#startGame\"",
            "",
            "accounts:",
            "  pool:",
            "    - username: \"a001\"",
            "      password: \"p001\"",
            "",
            "flow:",
            "  step_timeout_seconds: 120",
            "  click_retry: 3",
            "  template_threshold: 0.86",
            "  enter_game_wait_seconds: 30",
            "  channel_random_range: 3",
            "  force_kill_on_exit_fail: true",
            "  account_max_retry: 2",
            "",
            "window:",
            "  x: 0",
            "  y: 0",
            "  width: 1920",
            "  height: 1440",
            "  dpi_scale_percent: 150",
            "",
            "evidence:",
            "  dir: \"evidence\"",
            "  retention_days: 7",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def test_load_config_valid(tmp_path: Path) -> None:
    for name in DEFAULT_ANCHOR_FILES:
        target = tmp_path / "anchors" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, exe_path, roi_path)

    env_path = tmp_path / ".env"
    env_path.write_text("FLOW__ACCOUNT_MAX_RETRY=1\n", encoding="utf-8")

    config = load_config(
        config_path=config_path,
        env_path=env_path,
        base_dir=tmp_path,
    )

    assert config.launcher.exe_path == exe_path
    assert config.flow.account_max_retry == 1


def test_missing_anchors(tmp_path: Path) -> None:
    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, exe_path, roi_path)

    env_path = tmp_path / ".env"
    with pytest.raises(ValueError):
        load_config(
            config_path=config_path,
            env_path=env_path,
            base_dir=tmp_path,
        )


def test_load_config_required_anchors(tmp_path: Path) -> None:
    target = (
        tmp_path
        / "anchors"
        / "launcher_start_enabled"
        / "button.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")

    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, exe_path, roi_path)

    config = load_config(
        config_path=config_path,
        env_path=tmp_path / ".env",
        base_dir=tmp_path,
        required_anchors=["launcher_start_enabled/button.png"],
    )

    assert config.launcher.start_button_roi_name == "button"


def test_flow_keywords_fallback() -> None:
    flow = FlowConfig.model_validate(
        {
            "ocr_keywords": ["失败", "错误"],
        }
    )
    assert flow.exception_keywords == ["失败", "错误"]


def test_flow_window_visibility_defaults() -> None:
    flow = FlowConfig.model_validate({})
    assert flow.window_visibility_check_enabled is True
    assert flow.window_visible_ratio_min == 0.85


def test_flow_window_visible_ratio_min_invalid() -> None:
    with pytest.raises(ValidationError):
        FlowConfig.model_validate(
            {
                "window_visible_ratio_min": 1.2,
            }
        )


def test_load_config_exe_path_from_env(tmp_path: Path) -> None:
    for name in DEFAULT_ANCHOR_FILES:
        target = tmp_path / "anchors" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, None, roi_path)

    env_path = tmp_path / ".env"
    env_path.write_text(
        f"LAUNCHER__EXE_PATH={exe_path.as_posix()}\n",
        encoding="utf-8",
    )

    config = load_config(
        config_path=config_path,
        env_path=env_path,
        base_dir=tmp_path,
    )

    assert config.launcher.exe_path == exe_path


def test_launcher_lifecycle_mode_default_reuse(tmp_path: Path) -> None:
    for name in DEFAULT_ANCHOR_FILES:
        target = tmp_path / "anchors" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(config_path, exe_path, roi_path)

    config = load_config(
        config_path=config_path,
        env_path=tmp_path / ".env",
        base_dir=tmp_path,
    )

    assert config.launcher.lifecycle_mode == "reuse"


def test_launcher_lifecycle_mode_from_yaml(tmp_path: Path) -> None:
    for name in DEFAULT_ANCHOR_FILES:
        target = tmp_path / "anchors" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x", encoding="utf-8")

    exe_path = tmp_path / "launcher.exe"
    exe_path.write_text("x", encoding="utf-8")

    roi_dir = tmp_path / "anchors" / "launcher_start_enabled"
    roi_dir.mkdir(parents=True, exist_ok=True)
    roi_path = roi_dir / "roi.json"
    roi_path.write_text("{}", encoding="utf-8")

    config_path = tmp_path / "config.yaml"
    _write_config(
        config_path,
        exe_path,
        roi_path,
        lifecycle_mode="clean",
    )

    config = load_config(
        config_path=config_path,
        env_path=tmp_path / ".env",
        base_dir=tmp_path,
    )

    assert config.launcher.lifecycle_mode == "clean"
