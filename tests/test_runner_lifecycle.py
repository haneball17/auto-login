from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ocr_ops import OcrItem
import src.runner as runner


def _build_wait_game_config(lifecycle_mode: str) -> SimpleNamespace:
    return SimpleNamespace(
        launcher=SimpleNamespace(
            game_window_title_keyword="DNF Taiwan",
            lifecycle_mode=lifecycle_mode,
        ),
        flow=SimpleNamespace(step_timeout_seconds=10),
    )


def _build_web_failure_config(error_policy: str) -> SimpleNamespace:
    return SimpleNamespace(
        web=SimpleNamespace(
            browser_window_title_keyword="登录 · 猪咪云启动器",
            browser_process_name="msedge.exe",
        ),
        launcher=SimpleNamespace(
            game_window_title_keyword="DNF Taiwan",
            launcher_window_title_keyword="猪咪启动器",
            launcher_process_name="猪咪启动器.exe",
            exe_path=Path("launcher.exe"),
        ),
        flow=SimpleNamespace(
            error_policy=error_policy,
            ocr_region_ratio=0.6,
        ),
        evidence=SimpleNamespace(dir=Path("evidence")),
    )


def _build_ocr_exception_config(
    exception_keywords: list[str],
    clickable_keywords: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        launcher=SimpleNamespace(
            game_window_title_keyword="DNF Taiwan",
        ),
        flow=SimpleNamespace(
            exception_keywords=exception_keywords,
            clickable_keywords=clickable_keywords or [],
            ocr_keyword_min_score=0.5,
            ocr_region_ratio=0.6,
        ),
    )


def _build_visibility_config(
    enabled: bool = True,
    min_ratio: float = 0.85,
    auto_recover_enabled: bool = False,
    auto_recover_targets: list[str] | None = None,
    auto_recover_max_attempts: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        launcher=SimpleNamespace(
            game_window_title_keyword="DNF Taiwan",
            launcher_window_title_keyword="猪咪启动器",
        ),
        web=SimpleNamespace(
            browser_window_title_keyword="登录 · 猪咪云启动器",
        ),
        flow=SimpleNamespace(
            window_visibility_check_enabled=enabled,
            window_visible_ratio_min=min_ratio,
            window_auto_recover_enabled=auto_recover_enabled,
            window_auto_recover_targets=auto_recover_targets or ["game"],
            window_auto_recover_max_attempts=auto_recover_max_attempts,
            window_auto_recover_cooldown_seconds=0.0,
            window_auto_recover_padding_px=24,
            window_auto_recover_allow_resize=False,
            error_policy="restart",
            ocr_region_ratio=0.6,
        ),
        evidence=SimpleNamespace(dir=Path("evidence")),
    )


def test_wait_game_window_ready_clean_mode_should_cleanup(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(runner, "wait_game_window", lambda **_: 100)
    monkeypatch.setattr(
        runner,
        "activate_window",
        lambda hwnd: calls.append(("activate_window", hwnd)),
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_launcher_process",
        lambda *_: calls.append(("cleanup", "called")),
    )

    runner._wait_game_window_ready(_build_wait_game_config("clean"))

    assert ("activate_window", 100) in calls
    assert ("cleanup", "called") in calls


def test_wait_game_window_ready_reuse_mode_should_skip_cleanup(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    monkeypatch.setattr(runner, "wait_game_window", lambda **_: 200)
    monkeypatch.setattr(
        runner,
        "activate_window",
        lambda hwnd: calls.append(("activate_window", hwnd)),
    )
    monkeypatch.setattr(
        runner,
        "_cleanup_launcher_process",
        lambda *_: calls.append(("cleanup", "called")),
    )

    runner._wait_game_window_ready(_build_wait_game_config("reuse"))

    assert ("activate_window", 200) in calls
    assert ("cleanup", "called") not in calls


def test_recover_web_login_failure_manual_should_not_reset_launcher(
    monkeypatch,
) -> None:
    calls: list[str] = []
    config = _build_web_failure_config("manual")

    monkeypatch.setattr(
        runner,
        "save_ui_evidence",
        lambda **_: calls.append("save_ui_evidence"),
    )
    monkeypatch.setattr(
        runner,
        "kill_processes",
        lambda *_: calls.append("kill_processes"),
    )
    monkeypatch.setattr(
        runner,
        "_reset_launcher_process",
        lambda *_: calls.append("reset_launcher"),
    )

    runner._recover_web_login_failure(
        config,
        stage="网页登录",
        error=RuntimeError("mock"),
    )

    assert "save_ui_evidence" in calls
    assert "kill_processes" not in calls
    assert "reset_launcher" not in calls


def test_recover_web_login_failure_restart_should_reset_launcher(
    monkeypatch,
) -> None:
    calls: list[str] = []
    config = _build_web_failure_config("restart")

    def _mock_kill_processes(*_) -> int:
        calls.append("kill_browser")
        return 1

    monkeypatch.setattr(runner, "save_ui_evidence", lambda **_: None)
    monkeypatch.setattr(runner, "close_window_by_title", lambda *_: True)
    monkeypatch.setattr(runner, "kill_processes", _mock_kill_processes)
    monkeypatch.setattr(
        runner,
        "_reset_launcher_process",
        lambda *_: calls.append("reset_launcher"),
    )

    runner._recover_web_login_failure(
        config,
        stage="等待登录URL",
        error=RuntimeError("mock"),
    )

    assert "kill_browser" in calls
    assert "reset_launcher" in calls


def test_ocr_exception_flow_mailbox_should_treat_as_in_game(
    monkeypatch,
) -> None:
    config = _build_ocr_exception_config(
        exception_keywords=["邮件"],
        clickable_keywords=[],
    )
    items = [
        OcrItem(
            text="发送邮件",
            score=0.95,
            box=None,
            bbox=None,
        ),
        OcrItem(
            text="邮件保管箱",
            score=0.95,
            box=None,
            bbox=None,
        ),
    ]

    monkeypatch.setattr(runner, "ocr_window_items", lambda **_: items)
    monkeypatch.setattr(runner, "select_latest_active_window", lambda *_: None)
    monkeypatch.setattr(
        runner,
        "press_key",
        lambda *_: (_ for _ in ()).throw(AssertionError("不应触发键盘动作")),
    )

    scene = runner._ocr_exception_flow(
        config=config,
        expected_scene="进入游戏界面",
        scene_checkers=[],
    )

    assert scene == "进入游戏界面"


def test_ocr_exception_flow_should_skip_keyboard_actions(
    monkeypatch,
) -> None:
    config = _build_ocr_exception_config(
        exception_keywords=["错误"],
        clickable_keywords=[],
    )
    items = [
        OcrItem(
            text="错误",
            score=0.95,
            box=None,
            bbox=None,
        )
    ]
    calls: list[str] = []

    monkeypatch.setattr(runner, "ocr_window_items", lambda **_: items)
    monkeypatch.setattr(runner, "select_latest_active_window", lambda *_: None)
    monkeypatch.setattr(
        runner,
        "press_key",
        lambda key: calls.append(key),
    )

    scene = runner._ocr_exception_flow(
        config=config,
        expected_scene="角色选择界面",
        scene_checkers=[],
    )

    assert scene is None
    assert calls == []


def test_ensure_window_visibility_disabled_should_skip_checks(
    monkeypatch,
) -> None:
    config = _build_visibility_config(enabled=False)

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: (_ for _ in ()).throw(AssertionError("不应调用窗口检测")),
    )

    runner._ensure_window_visibility(config, stage="测试阶段")


def test_ensure_window_visibility_should_fail_when_ratio_low(
    monkeypatch,
) -> None:
    config = _build_visibility_config(enabled=True, min_ratio=0.9)

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: (0, 0, 1000, 800),
    )
    monkeypatch.setattr(
        runner,
        "get_virtual_screen_rect",
        lambda: (0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        runner,
        "compute_visible_ratio",
        lambda *_: 0.5,
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(kwargs["reason"])
        ),
    )

    with pytest.raises(RuntimeError, match="窗口可见比例不足"):
        runner._ensure_window_visibility(config, stage="测试阶段")


def test_ensure_window_visibility_should_pass_when_ratio_enough(
    monkeypatch,
) -> None:
    config = _build_visibility_config(enabled=True, min_ratio=0.6)

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: (0, 0, 1000, 800),
    )
    monkeypatch.setattr(
        runner,
        "get_virtual_screen_rect",
        lambda: (0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        runner,
        "compute_visible_ratio",
        lambda *_: 0.9,
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("可见比例足够时不应失败")
        ),
    )

    runner._ensure_window_visibility(config, stage="测试阶段")


def test_ensure_window_visibility_should_recover_then_pass(
    monkeypatch,
) -> None:
    config = _build_visibility_config(
        enabled=True,
        min_ratio=0.85,
        auto_recover_enabled=True,
        auto_recover_targets=["game"],
        auto_recover_max_attempts=2,
    )
    calls: list[str] = []
    window_rects = [
        (-300, 0, 1000, 800),
        (0, 0, 1000, 800),
    ]

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: window_rects.pop(0),
    )
    monkeypatch.setattr(
        runner,
        "get_virtual_screen_rect",
        lambda: (0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        runner,
        "compute_visible_ratio",
        lambda rect, *_: 0.7 if rect[0] < 0 else 0.95,
    )
    monkeypatch.setattr(
        runner,
        "recover_window_to_visible",
        lambda *_, **__: calls.append("recover") or {"success": True},
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("复位成功后不应失败")
        ),
    )

    runner._ensure_window_visibility(config, stage="测试阶段")
    assert calls == ["recover"]


def test_ensure_window_visibility_should_fail_after_recover_exhausted(
    monkeypatch,
) -> None:
    config = _build_visibility_config(
        enabled=True,
        min_ratio=0.85,
        auto_recover_enabled=True,
        auto_recover_targets=["game"],
        auto_recover_max_attempts=2,
    )
    calls: list[str] = []

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: (-300, 0, 1000, 800),
    )
    monkeypatch.setattr(
        runner,
        "get_virtual_screen_rect",
        lambda: (0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        runner,
        "compute_visible_ratio",
        lambda *_: 0.7,
    )
    monkeypatch.setattr(
        runner,
        "recover_window_to_visible",
        lambda *_, **__: calls.append("recover")
        or {"success": False, "reason": "mock"},
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(kwargs["reason"])
        ),
    )

    with pytest.raises(RuntimeError, match="窗口可见比例不足"):
        runner._ensure_window_visibility(config, stage="测试阶段")
    assert calls == ["recover", "recover"]


def test_ensure_window_visibility_launcher_should_not_recover_when_target_game(
    monkeypatch,
) -> None:
    config = _build_visibility_config(
        enabled=True,
        min_ratio=0.9,
        auto_recover_enabled=True,
        auto_recover_targets=["game"],
    )
    calls: list[str] = []

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: (0, 0, 1000, 800),
    )
    monkeypatch.setattr(
        runner,
        "get_virtual_screen_rect",
        lambda: (0, 0, 1920, 1080),
    )
    monkeypatch.setattr(
        runner,
        "compute_visible_ratio",
        lambda *_: 0.5,
    )
    monkeypatch.setattr(
        runner,
        "recover_window_to_visible",
        lambda *_, **__: calls.append("recover") or {"success": True},
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(kwargs["reason"])
        ),
    )

    with pytest.raises(RuntimeError, match="窗口可见比例不足"):
        runner._ensure_window_visibility(
            config,
            stage="测试阶段",
            window_title="猪咪启动器",
        )
    assert calls == []


def test_resolve_click_center_should_pass_when_point_visible(
    monkeypatch,
) -> None:
    config = _build_visibility_config(
        auto_recover_enabled=True,
        auto_recover_targets=["game"],
    )
    calls: list[str] = []

    monkeypatch.setattr(runner, "get_window_rect", lambda *_: (0, 0, 1000, 800))
    monkeypatch.setattr(runner, "load_roi_region", lambda *_: (0, 0, 100, 40))
    monkeypatch.setattr(runner, "roi_center", lambda *_args, **_kwargs: (100, 100))
    monkeypatch.setattr(
        runner,
        "_get_window_visible_rect",
        lambda *_: (0, 0, 1920, 1040),
    )
    monkeypatch.setattr(
        runner,
        "recover_window_to_visible",
        lambda *_, **__: calls.append("recover") or {"success": True},
    )

    center = runner._resolve_click_center_with_visibility_check(
        config=config,
        stage="测试点击点可见性",
        window_title="DNF Taiwan",
        roi_path=Path("mock.json"),
        roi_name="button",
    )
    assert center == (100, 100)
    assert calls == []


def test_resolve_click_center_should_recover_and_recalculate(
    monkeypatch,
) -> None:
    config = _build_visibility_config(
        auto_recover_enabled=True,
        auto_recover_targets=["game"],
        auto_recover_max_attempts=2,
    )
    calls: list[str] = []
    window_rects = [
        (0, 1000, 1000, 800),
        (0, 0, 1000, 800),
    ]

    monkeypatch.setattr(
        runner,
        "get_window_rect",
        lambda *_: window_rects.pop(0),
    )
    monkeypatch.setattr(runner, "load_roi_region", lambda *_: (0, 0, 100, 40))
    monkeypatch.setattr(
        runner,
        "roi_center",
        lambda _roi, offset=(0, 0): (offset[0] + 50, offset[1] + 50),
    )
    monkeypatch.setattr(
        runner,
        "_get_window_visible_rect",
        lambda *_: (0, 0, 1920, 1040),
    )
    monkeypatch.setattr(
        runner,
        "recover_window_to_visible",
        lambda *_, **__: calls.append("recover")
        or {"success": True, "reason": "mock"},
    )

    center = runner._resolve_click_center_with_visibility_check(
        config=config,
        stage="测试点击点可见性",
        window_title="DNF Taiwan",
        roi_path=Path("mock.json"),
        roi_name="button",
    )
    assert center == (50, 50)
    assert calls == ["recover"]


def test_click_roi_button_should_use_click_strategy_success(
    monkeypatch,
) -> None:
    config = _build_visibility_config(enabled=True)

    monkeypatch.setattr(runner, "_ensure_window_visibility", lambda *_, **__: None)
    monkeypatch.setattr(
        runner,
        "click_roi_with_strategy",
        lambda **_: runner.ClickResult(
            success=True,
            attempts=[],
            final_reason="ok",
            success_point=(100, 100),
            success_click_time=1.0,
        ),
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("点击成功时不应触发失败处理")
        ),
    )

    runner._click_roi_button(
        config,
        Path("mock.json"),
        "button_startgame",
    )


def test_click_roi_button_should_fail_when_click_strategy_failed(
    monkeypatch,
) -> None:
    config = _build_visibility_config(enabled=True)

    monkeypatch.setattr(runner, "_ensure_window_visibility", lambda *_, **__: None)
    monkeypatch.setattr(
        runner,
        "click_roi_with_strategy",
        lambda **_: runner.ClickResult(
            success=False,
            attempts=[],
            final_reason="verify_failed",
        ),
    )
    monkeypatch.setattr(
        runner,
        "_handle_step_failure",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError(kwargs["reason"])
        ),
    )

    with pytest.raises(RuntimeError, match="点击按钮失败"):
        runner._click_roi_button(
            config,
            Path("mock.json"),
            "button_startgame",
        )
