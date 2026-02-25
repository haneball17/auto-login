from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .process_ops import (
    activate_window,
    get_window_work_rect,
    recover_window_to_visible,
    select_latest_active_window,
)
from .ui_ops import (
    click_point,
    get_virtual_screen_rect,
    get_window_rect,
    is_point_in_rect,
    load_roi_region,
    roi_center,
)

logger = logging.getLogger("auto_login")

VerifyAction = Callable[[tuple[int, int], float], bool]
FallbackAction = Callable[[], bool]
PointProvider = Callable[[], tuple[int, int]]


@dataclass(frozen=True)
class ClickAttemptResult:
    success: bool
    point: tuple[int, int]
    round_index: int
    offset_index: int
    reason: str


@dataclass(frozen=True)
class ClickResult:
    success: bool
    attempts: list[ClickAttemptResult]
    final_reason: str
    success_point: tuple[int, int] | None = None
    success_click_time: float | None = None


def click_roi_with_strategy(
    *,
    flow: object,
    window_title: str,
    roi_path: Path,
    roi_name: str,
    stage: str,
    target_name: str,
    recover_enabled: bool,
    verify_action: VerifyAction | None = None,
    fallback_action: FallbackAction | None = None,
) -> ClickResult:
    def _point_provider() -> tuple[int, int]:
        window_rect = get_window_rect(window_title)
        roi_region = load_roi_region(roi_path, roi_name)
        return roi_center(roi_region, offset=(window_rect[0], window_rect[1]))

    return click_point_with_strategy(
        flow=flow,
        window_title=window_title,
        point_provider=_point_provider,
        stage=stage,
        target_name=target_name,
        recover_enabled=recover_enabled,
        verify_action=verify_action,
        fallback_action=fallback_action,
    )


def click_point_with_strategy(
    *,
    flow: object,
    window_title: str,
    point_provider: PointProvider,
    stage: str,
    target_name: str,
    recover_enabled: bool,
    verify_action: VerifyAction | None = None,
    fallback_action: FallbackAction | None = None,
) -> ClickResult:
    if not bool(getattr(flow, "click_strategy_enabled", True)):
        return _click_without_strategy(
            window_title=window_title,
            point_provider=point_provider,
            verify_action=verify_action,
        )

    max_attempts = max(1, int(getattr(flow, "click_max_attempts", 3)))
    guard_padding = max(0, int(getattr(flow, "click_point_guard_padding_px", 0)))
    post_check_delay_seconds = max(
        0.0,
        float(getattr(flow, "click_post_check_delay_ms", 0)) / 1000.0,
    )
    verify_foreground_enabled = bool(
        getattr(flow, "click_verify_foreground_enabled", True)
    )
    foreground_wait_seconds = max(
        0.0,
        float(getattr(flow, "click_foreground_wait_ms", 0)) / 1000.0,
    )
    ocr_fallback_enabled = bool(getattr(flow, "click_ocr_fallback_enabled", True))

    candidate_offsets = _build_candidate_offsets(flow)
    backoff_seconds = _build_backoff_seconds(flow)
    attempts: list[ClickAttemptResult] = []

    for round_index in range(1, max_attempts + 1):
        if not _activate_target_window(
            window_title,
            wait_seconds=foreground_wait_seconds,
            verify_foreground=verify_foreground_enabled,
        ):
            attempts.append(
                ClickAttemptResult(
                    success=False,
                    point=(0, 0),
                    round_index=round_index,
                    offset_index=-1,
                    reason="activate_or_foreground_check_failed",
                )
            )
            _sleep_backoff(round_index, max_attempts, backoff_seconds)
            continue

        base_point, visible_rect, base_reason = _resolve_base_point_with_recover(
            flow=flow,
            window_title=window_title,
            point_provider=point_provider,
            recover_enabled=recover_enabled,
            guard_padding=guard_padding,
            stage=stage,
            target_name=target_name,
        )
        if base_point is None:
            attempts.append(
                ClickAttemptResult(
                    success=False,
                    point=(0, 0),
                    round_index=round_index,
                    offset_index=-1,
                    reason=base_reason,
                )
            )
            _sleep_backoff(round_index, max_attempts, backoff_seconds)
            continue

        for offset_index, (dx, dy) in enumerate(candidate_offsets):
            point = (base_point[0] + dx, base_point[1] + dy)
            if not _is_point_clickable(point, visible_rect, guard_padding):
                attempts.append(
                    ClickAttemptResult(
                        success=False,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason=(
                            "candidate_outside_work_rect"
                            f":visible_rect={visible_rect},guard={guard_padding}"
                        ),
                    )
                )
                continue

            click_time = time.time()
            try:
                click_point(point)
            except Exception as exc:
                attempts.append(
                    ClickAttemptResult(
                        success=False,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason=f"click_failed:{exc}",
                    )
                )
                continue

            if post_check_delay_seconds > 0:
                time.sleep(post_check_delay_seconds)

            if verify_foreground_enabled and not _is_window_in_foreground(window_title):
                attempts.append(
                    ClickAttemptResult(
                        success=False,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason="foreground_lost_after_click",
                    )
                )
                continue

            if verify_action is None:
                attempts.append(
                    ClickAttemptResult(
                        success=True,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason="ok_without_verify",
                    )
                )
                logger.info(
                    "点击成功: stage=%s, target=%s, round=%d, offset=%d, point=%s",
                    stage,
                    target_name,
                    round_index,
                    offset_index,
                    point,
                )
                return ClickResult(
                    success=True,
                    attempts=attempts,
                    final_reason="ok_without_verify",
                    success_point=point,
                    success_click_time=click_time,
                )

            verify_passed = False
            try:
                verify_passed = bool(verify_action(point, click_time))
            except Exception as exc:
                attempts.append(
                    ClickAttemptResult(
                        success=False,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason=f"verify_error:{exc}",
                    )
                )
                continue

            if verify_passed:
                attempts.append(
                    ClickAttemptResult(
                        success=True,
                        point=point,
                        round_index=round_index,
                        offset_index=offset_index,
                        reason="ok_verified",
                    )
                )
                logger.info(
                    "点击验证成功: stage=%s, target=%s, round=%d, offset=%d, point=%s",
                    stage,
                    target_name,
                    round_index,
                    offset_index,
                    point,
                )
                return ClickResult(
                    success=True,
                    attempts=attempts,
                    final_reason="ok_verified",
                    success_point=point,
                    success_click_time=click_time,
                )

            attempts.append(
                ClickAttemptResult(
                    success=False,
                    point=point,
                    round_index=round_index,
                    offset_index=offset_index,
                    reason="verify_failed",
                )
            )

        _sleep_backoff(round_index, max_attempts, backoff_seconds)

    if ocr_fallback_enabled and fallback_action is not None:
        try:
            recovered = bool(fallback_action())
        except Exception as exc:
            recovered = False
            attempts.append(
                ClickAttemptResult(
                    success=False,
                    point=(0, 0),
                    round_index=max_attempts,
                    offset_index=-2,
                    reason=f"ocr_fallback_error:{exc}",
                )
            )
        if recovered:
            attempts.append(
                ClickAttemptResult(
                    success=True,
                    point=(0, 0),
                    round_index=max_attempts,
                    offset_index=-2,
                    reason="ocr_fallback_success",
                )
            )
            logger.warning(
                "点击主链路失败后 OCR 兜底成功: stage=%s, target=%s",
                stage,
                target_name,
            )
            return ClickResult(
                success=True,
                attempts=attempts,
                final_reason="ocr_fallback_success",
            )

    final_reason = attempts[-1].reason if attempts else "click_no_attempt"
    logger.warning(
        "点击失败: stage=%s, target=%s, attempts=%d, reason=%s",
        stage,
        target_name,
        len(attempts),
        final_reason,
    )
    return ClickResult(
        success=False,
        attempts=attempts,
        final_reason=final_reason,
    )


def _click_without_strategy(
    window_title: str,
    point_provider: PointProvider,
    verify_action: VerifyAction | None,
) -> ClickResult:
    try:
        point = point_provider()
    except Exception as exc:
        return ClickResult(
            success=False,
            attempts=[],
            final_reason=f"resolve_point_failed:{exc}",
        )

    try:
        click_point(point)
    except Exception as exc:
        return ClickResult(
            success=False,
            attempts=[
                ClickAttemptResult(
                    success=False,
                    point=point,
                    round_index=1,
                    offset_index=0,
                    reason=f"click_failed:{exc}",
                )
            ],
            final_reason=f"click_failed:{exc}",
        )

    click_time = time.time()
    if verify_action is not None:
        try:
            if not verify_action(point, click_time):
                return ClickResult(
                    success=False,
                    attempts=[
                        ClickAttemptResult(
                            success=False,
                            point=point,
                            round_index=1,
                            offset_index=0,
                            reason="verify_failed",
                        )
                    ],
                    final_reason="verify_failed",
                )
        except Exception as exc:
            return ClickResult(
                success=False,
                attempts=[
                    ClickAttemptResult(
                        success=False,
                        point=point,
                        round_index=1,
                        offset_index=0,
                        reason=f"verify_error:{exc}",
                    )
                ],
                final_reason=f"verify_error:{exc}",
            )

    return ClickResult(
        success=True,
        attempts=[
            ClickAttemptResult(
                success=True,
                point=point,
                round_index=1,
                offset_index=0,
                reason=("ok_without_verify" if verify_action is None else "ok_verified"),
            )
        ],
        final_reason=("ok_without_verify" if verify_action is None else "ok_verified"),
        success_point=point,
        success_click_time=click_time,
    )


def _activate_target_window(
    window_title: str,
    wait_seconds: float,
    verify_foreground: bool,
) -> bool:
    hwnd = select_latest_active_window(window_title)
    if hwnd is None:
        logger.warning("点击前未找到目标窗口: %s", window_title)
        return False

    try:
        activate_window(hwnd)
    except Exception as exc:
        logger.warning("点击前激活窗口失败: %s", exc)
        return False

    if wait_seconds > 0:
        time.sleep(wait_seconds)

    if verify_foreground and not _is_window_in_foreground(window_title):
        logger.warning("点击前前台窗口不匹配: %s", window_title)
        return False
    return True


def _is_window_in_foreground(window_title: str) -> bool:
    try:
        import win32gui
    except Exception:
        # 非 Windows 环境无法校验前台窗口，默认放行。
        return True

    try:
        hwnd = win32gui.GetForegroundWindow()
    except Exception:
        return False
    if not hwnd:
        return False
    try:
        title = win32gui.GetWindowText(hwnd) or ""
    except Exception:
        return False
    return window_title in title


def _resolve_base_point_with_recover(
    *,
    flow: object,
    window_title: str,
    point_provider: PointProvider,
    recover_enabled: bool,
    guard_padding: int,
    stage: str,
    target_name: str,
) -> tuple[tuple[int, int] | None, tuple[int, int, int, int], str]:
    max_recover_attempts = max(
        1,
        int(getattr(flow, "window_auto_recover_max_attempts", 1)),
    )
    recover_cooldown_seconds = max(
        0.0,
        float(getattr(flow, "window_auto_recover_cooldown_seconds", 0.0)),
    )
    recover_padding_px = max(
        0,
        int(getattr(flow, "window_auto_recover_padding_px", 0)),
    )
    allow_resize = bool(getattr(flow, "window_auto_recover_allow_resize", False))

    visible_rect = _get_window_visible_rect(window_title)
    last_reason = "resolve_base_point_failed"

    for attempt in range(1, max_recover_attempts + 1):
        try:
            base_point = point_provider()
        except Exception as exc:
            last_reason = f"resolve_base_point_failed:{exc}"
            break

        visible_rect = _get_window_visible_rect(window_title)
        if _is_point_clickable(base_point, visible_rect, guard_padding):
            return base_point, visible_rect, "ok"

        last_reason = (
            "base_point_outside_work_rect"
            f":point={base_point},visible_rect={visible_rect},guard={guard_padding}"
        )

        if not recover_enabled:
            break
        if attempt >= max_recover_attempts:
            break

        recover_result = recover_window_to_visible(
            window_title,
            padding_px=recover_padding_px,
            allow_resize=allow_resize,
        )
        logger.warning(
            "点击点不在工作区，尝试窗口复位: stage=%s, target=%s, "
            "attempt=%d/%d, point=%s, visible_rect=%s, reason=%s",
            stage,
            target_name,
            attempt,
            max_recover_attempts,
            base_point,
            visible_rect,
            recover_result.get("reason"),
        )
        if recover_cooldown_seconds > 0:
            time.sleep(recover_cooldown_seconds)

    return None, visible_rect, last_reason


def _build_candidate_offsets(flow: object) -> list[tuple[int, int]]:
    raw = getattr(flow, "click_candidates", [(0, 0)])
    offsets: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        offsets.append((int(item[0]), int(item[1])))
    if not offsets:
        offsets = [(0, 0)]
    return offsets


def _build_backoff_seconds(flow: object) -> list[float]:
    raw = getattr(flow, "click_backoff_ms", [100, 250, 500])
    values: list[float] = []
    for item in raw:
        try:
            value = int(item)
        except Exception:
            continue
        if value < 0:
            continue
        values.append(float(value) / 1000.0)
    if not values:
        return [0.0]
    return values


def _sleep_backoff(
    round_index: int,
    max_attempts: int,
    backoff_seconds: list[float],
) -> None:
    if round_index >= max_attempts:
        return
    delay = backoff_seconds[min(round_index - 1, len(backoff_seconds) - 1)]
    if delay > 0:
        time.sleep(delay)


def _get_window_visible_rect(window_title: str) -> tuple[int, int, int, int]:
    try:
        return get_window_work_rect(window_title)
    except Exception:
        return get_virtual_screen_rect()


def _is_point_clickable(
    point: tuple[int, int],
    visible_rect: tuple[int, int, int, int],
    guard_padding: int,
) -> bool:
    if not is_point_in_rect(point, visible_rect):
        return False
    if guard_padding <= 0:
        return True

    x, y = point
    left, top, width, height = visible_rect
    if width <= guard_padding * 2 or height <= guard_padding * 2:
        return True

    return (
        left + guard_padding <= x < left + width - guard_padding
        and top + guard_padding <= y < top + height - guard_padding
    )
