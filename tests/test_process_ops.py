from __future__ import annotations

from src.process_ops import _compute_recovered_window_rect


def test_compute_recovered_window_rect_should_clamp_position() -> None:
    window_rect = (-300, -200, 1000, 800)
    virtual_rect = (0, 0, 1920, 1080)

    result = _compute_recovered_window_rect(
        window_rect=window_rect,
        visible_rect=virtual_rect,
        padding_px=24,
        allow_resize=False,
    )

    assert result == (24, 24, 1000, 800)


def test_compute_recovered_window_rect_should_resize_when_enabled() -> None:
    window_rect = (0, 0, 3000, 2000)
    virtual_rect = (0, 0, 1920, 1080)

    result = _compute_recovered_window_rect(
        window_rect=window_rect,
        visible_rect=virtual_rect,
        padding_px=24,
        allow_resize=True,
    )

    assert result == (24, 24, 1872, 1032)
