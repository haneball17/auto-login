from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np

logger = logging.getLogger("auto_login")


@dataclass(frozen=True)
class MatchResult:
    found: bool
    score: float
    center: tuple[int, int] | None


@dataclass(frozen=True)
class BlueDominanceRule:
    min_blue: int = 120
    dominance: int = 20


@dataclass(frozen=True)
class RoiRect:
    x: int
    y: int
    width: int
    height: int


def capture_screen(region: tuple[int, int, int, int] | None = None) -> np.ndarray:
    import pyautogui

    screenshot = pyautogui.screenshot(region=region)
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)


def match_template(
    image: np.ndarray,
    template: np.ndarray,
    threshold: float,
    offset: tuple[int, int] = (0, 0),
) -> MatchResult:
    result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)

    if max_val < threshold:
        return MatchResult(False, float(max_val), None)

    center_x = int(max_loc[0] + template.shape[1] / 2 + offset[0])
    center_y = int(max_loc[1] + template.shape[0] / 2 + offset[1])
    return MatchResult(True, float(max_val), (center_x, center_y))


def is_blue_dominant(image: np.ndarray, rule: BlueDominanceRule) -> bool:
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("图像必须为 BGR 三通道")

    bgr_mean = image.mean(axis=(0, 1))
    blue = bgr_mean[0]
    green = bgr_mean[1]
    red = bgr_mean[2]

    if blue < rule.min_blue:
        return False

    return bool(blue - max(green, red) >= rule.dominance)


def wait_launcher_start_enabled(
    template_path: Path,
    region: tuple[int, int, int, int] | None,
    timeout_seconds: int = 60,
    threshold: float = 0.86,
    poll_interval: float = 1.0,
    color_rule: BlueDominanceRule | None = None,
    roi_path: Path | None = None,
    roi_name: str = "button",
    window_title: str | None = None,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")

    template = _load_template(template_path)
    roi_region = None
    if roi_path is not None:
        roi_region = load_roi_region(roi_path, roi_name)
        if window_title is None and region is None:
            raise ValueError("使用 roi.json 时必须提供 window_title 或 region")
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        image, offset = _capture_with_roi(region, roi_region, window_title)

        if color_rule is not None:
            if is_blue_dominant(image, color_rule):
                logger.info("检测到启动按钮变为可用颜色")
                return True

        result = match_template(
            image=image,
            template=template,
            threshold=threshold,
            offset=offset,
        )
        if result.found:
            logger.info("检测到启动按钮模板匹配成功，score=%.3f", result.score)
            return True

        time.sleep(poll_interval)

    logger.warning("等待启动按钮可用超时")
    return False


def _load_template(template_path: Path) -> np.ndarray:
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f"模板文件不存在或无法读取: {template_path}")
    return template


def load_roi_region(roi_path: Path, roi_name: str) -> tuple[int, int, int, int]:
    roi_data = _load_roi_json(roi_path)
    roi = _find_roi(roi_data.get("rois", []), roi_name)

    x = int(round(roi["x"]))
    y = int(round(roi["y"]))
    width = int(round(roi["w"]))
    height = int(round(roi["h"]))
    return (x, y, width, height)


def _load_roi_json(roi_path: Path) -> dict:
    if not roi_path.is_file():
        raise FileNotFoundError(f"ROI 文件不存在: {roi_path}")
    return json.loads(roi_path.read_text(encoding="utf-8"))


def _find_roi(rois: list[dict], roi_name: str) -> dict:
    for roi in rois:
        if roi.get("name") == roi_name:
            return roi
    raise ValueError(f"ROI 未找到: {roi_name}")


def _capture_with_roi(
    region: tuple[int, int, int, int] | None,
    roi_region: tuple[int, int, int, int] | None,
    window_title: str | None,
) -> tuple[np.ndarray, tuple[int, int]]:
    if window_title is not None:
        window_image, window_rect = capture_window(window_title)
        if roi_region is None:
            return window_image, (window_rect[0], window_rect[1])
        roi_image = _crop_region(window_image, roi_region)
        offset = (
            window_rect[0] + roi_region[0],
            window_rect[1] + roi_region[1],
        )
        return roi_image, offset

    image = capture_screen(region=region)
    offset = (region[0], region[1]) if region else (0, 0)
    if roi_region is not None:
        roi_image = _crop_region(image, roi_region)
        offset = (offset[0] + roi_region[0], offset[1] + roi_region[1])
        return roi_image, offset
    return image, offset


def _crop_region(
    image: np.ndarray,
    region: tuple[int, int, int, int],
) -> np.ndarray:
    x, y, width, height = region
    x_end = max(x, 0) + max(width, 0)
    y_end = max(y, 0) + max(height, 0)
    return image[max(y, 0):y_end, max(x, 0):x_end]


def capture_window(title_keyword: str) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    rect = get_window_rect(title_keyword)
    return capture_screen(region=rect), rect


def get_window_rect(title_keyword: str) -> tuple[int, int, int, int]:
    try:
        import win32gui
    except ImportError as exc:
        raise RuntimeError("win32gui 不可用，无法定位窗口") from exc

    matches: list[tuple[int, tuple[int, int, int, int]]] = []

    def _enum_handler(hwnd: int, extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title_keyword in title:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            matches.append((hwnd, (left, top, right, bottom)))

    win32gui.EnumWindows(_enum_handler, None)
    if not matches:
        raise ValueError(f"未找到窗口: {title_keyword}")

    _, rect = matches[0]
    left, top, right, bottom = rect
    return (left, top, right - left, bottom - top)
