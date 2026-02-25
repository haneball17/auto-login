from __future__ import annotations

from types import SimpleNamespace

import src.click_ops as click_ops


def _build_flow(**overrides) -> SimpleNamespace:
    base = {
        "click_strategy_enabled": True,
        "click_verify_foreground_enabled": False,
        "click_foreground_wait_ms": 0,
        "click_candidates": [(0, 0)],
        "click_max_attempts": 3,
        "click_backoff_ms": [100, 250, 500],
        "click_post_check_delay_ms": 0,
        "click_point_guard_padding_px": 0,
        "click_ocr_fallback_enabled": True,
        "window_auto_recover_max_attempts": 2,
        "window_auto_recover_cooldown_seconds": 0.0,
        "window_auto_recover_padding_px": 24,
        "window_auto_recover_allow_resize": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_click_point_with_strategy_should_try_next_offset(monkeypatch) -> None:
    flow = _build_flow(
        click_max_attempts=1,
        click_candidates=[(0, 0), (5, 0)],
        click_backoff_ms=[0],
    )
    clicked_points: list[tuple[int, int]] = []

    monkeypatch.setattr(
        click_ops,
        "_activate_target_window",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        click_ops,
        "_resolve_base_point_with_recover",
        lambda **_kwargs: ((100, 100), (0, 0, 500, 400), "ok"),
    )
    monkeypatch.setattr(
        click_ops,
        "click_point",
        lambda point: clicked_points.append(point),
    )

    result = click_ops.click_point_with_strategy(
        flow=flow,
        window_title="DNF Taiwan",
        point_provider=lambda: (100, 100),
        stage="测试点击",
        target_name="mock",
        recover_enabled=True,
        verify_action=lambda point, _click_time: point == (105, 100),
    )

    assert result.success is True
    assert clicked_points == [(100, 100), (105, 100)]
    assert result.success_point == (105, 100)


def test_resolve_base_point_with_recover_should_retry(monkeypatch) -> None:
    flow = _build_flow(
        window_auto_recover_max_attempts=2,
        window_auto_recover_cooldown_seconds=0.0,
    )
    calls: list[str] = []
    points = [(195, 195), (100, 100)]

    monkeypatch.setattr(
        click_ops,
        "_get_window_visible_rect",
        lambda *_: (0, 0, 200, 200),
    )
    monkeypatch.setattr(
        click_ops,
        "recover_window_to_visible",
        lambda *_args, **_kwargs: calls.append("recover") or {"reason": "mock"},
    )

    base_point, visible_rect, reason = click_ops._resolve_base_point_with_recover(
        flow=flow,
        window_title="DNF Taiwan",
        point_provider=lambda: points.pop(0),
        recover_enabled=True,
        guard_padding=10,
        stage="测试阶段",
        target_name="mock",
    )

    assert base_point == (100, 100)
    assert visible_rect == (0, 0, 200, 200)
    assert reason == "ok"
    assert calls == ["recover"]


def test_click_point_with_strategy_should_backoff(monkeypatch) -> None:
    flow = _build_flow(
        click_max_attempts=3,
        click_candidates=[(0, 0)],
        click_backoff_ms=[100, 200, 500],
    )
    sleep_calls: list[float] = []

    monkeypatch.setattr(
        click_ops,
        "_activate_target_window",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        click_ops,
        "_resolve_base_point_with_recover",
        lambda **_kwargs: ((100, 100), (0, 0, 500, 400), "ok"),
    )
    monkeypatch.setattr(click_ops, "click_point", lambda *_: None)
    monkeypatch.setattr(click_ops.time, "sleep", lambda delay: sleep_calls.append(delay))

    result = click_ops.click_point_with_strategy(
        flow=flow,
        window_title="DNF Taiwan",
        point_provider=lambda: (100, 100),
        stage="测试点击",
        target_name="mock",
        recover_enabled=True,
        verify_action=lambda _point, _click_time: False,
    )

    assert result.success is False
    assert sleep_calls == [0.1, 0.2]


def test_click_roi_with_strategy_should_resolve_roi_center(monkeypatch) -> None:
    flow = _build_flow(click_strategy_enabled=False)
    clicked_points: list[tuple[int, int]] = []

    monkeypatch.setattr(click_ops, "get_window_rect", lambda *_: (100, 200, 800, 600))
    monkeypatch.setattr(click_ops, "load_roi_region", lambda *_: (10, 20, 100, 40))
    monkeypatch.setattr(
        click_ops,
        "click_point",
        lambda point: clicked_points.append(point),
    )

    result = click_ops.click_roi_with_strategy(
        flow=flow,
        window_title="DNF Taiwan",
        roi_path=None,
        roi_name="button",
        stage="测试点击",
        target_name="mock",
        recover_enabled=True,
    )

    assert result.success is True
    assert result.success_point == (160, 240)
    assert clicked_points == [(160, 240)]


def test_click_point_with_strategy_should_use_ocr_fallback(monkeypatch) -> None:
    flow = _build_flow(
        click_max_attempts=1,
        click_candidates=[(0, 0)],
        click_backoff_ms=[0],
        click_ocr_fallback_enabled=True,
    )

    monkeypatch.setattr(
        click_ops,
        "_activate_target_window",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        click_ops,
        "_resolve_base_point_with_recover",
        lambda **_kwargs: ((100, 100), (0, 0, 500, 400), "ok"),
    )
    monkeypatch.setattr(click_ops, "click_point", lambda *_: None)

    result = click_ops.click_point_with_strategy(
        flow=flow,
        window_title="DNF Taiwan",
        point_provider=lambda: (100, 100),
        stage="测试点击",
        target_name="mock",
        recover_enabled=True,
        verify_action=lambda _point, _click_time: False,
        fallback_action=lambda: True,
    )

    assert result.success is True
    assert result.final_reason == "ocr_fallback_success"
