from __future__ import annotations

import json
import logging
import math
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


def roi_center(
    roi_region: tuple[int, int, int, int],
    offset: tuple[int, int] = (0, 0),
) -> tuple[int, int]:
    x, y, width, height = roi_region
    center_x = int(x + width / 2 + offset[0])
    center_y = int(y + height / 2 + offset[1])
    return (center_x, center_y)


def expand_roi_region(
    roi_region: tuple[int, int, int, int],
    expand_ratio: float,
    bounds: tuple[int, int],
) -> tuple[int, int, int, int]:
    x, y, width, height = roi_region
    expand_ratio = max(0.0, expand_ratio)
    expand_w = int(width * expand_ratio)
    expand_h = int(height * expand_ratio)
    new_x = x - expand_w
    new_y = y - expand_h
    new_w = width + expand_w * 2
    new_h = height + expand_h * 2
    max_w, max_h = bounds
    clamped_x = max(0, min(new_x, max_w))
    clamped_y = max(0, min(new_y, max_h))
    clamped_w = max(1, min(new_w, max_w - clamped_x))
    clamped_h = max(1, min(new_h, max_h - clamped_y))
    return (clamped_x, clamped_y, clamped_w, clamped_h)


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
    last_report = 0.0
    logged_shape = False
    logged_size_mismatch = False
    logged_size_mismatch = False
    logged_window_missing = False

    while time.time() < deadline:
        try:
            image, offset = _capture_with_roi(region, roi_region, window_title)
        except ValueError as exc:
            if not logged_window_missing:
                logger.warning("启动按钮截图失败: %s", exc)
                logged_window_missing = True
            time.sleep(poll_interval)
            continue
        img_height, img_width = image.shape[:2]
        tpl_height, tpl_width = template.shape[:2]
        if img_height < tpl_height or img_width < tpl_width:
            if not logged_size_mismatch:
                logger.error(
                    "启动按钮截图区域小于模板尺寸，无法匹配: image=%dx%d, template=%dx%d",
                    img_width,
                    img_height,
                    tpl_width,
                    tpl_height,
                )
                logged_size_mismatch = True
            time.sleep(poll_interval)
            continue
        if not logged_shape:
            logger.info(
                "启动按钮检测参数: roi=%s, image=%dx%d, template=%dx%d, threshold=%.3f",
                roi_region,
                img_width,
                img_height,
                tpl_width,
                tpl_height,
                threshold,
            )
            logged_shape = True

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
        now = time.time()
        if now - last_report >= max(5.0, poll_interval):
            logger.info("启动按钮模板匹配中: score=%.3f", result.score)
            last_report = now
        logger.debug("启动按钮模板匹配得分=%.3f", result.score)
        if result.found:
            logger.info("检测到启动按钮模板匹配成功，score=%.3f", result.score)
            return True

        time.sleep(poll_interval)

    logger.warning("等待启动按钮可用超时")
    return False


def wait_template_match(
    template_path: Path,
    timeout_seconds: int,
    threshold: float,
    poll_interval: float = 1.0,
    roi_path: Path | None = None,
    roi_name: str = "title",
    window_title: str | None = None,
    region: tuple[int, int, int, int] | None = None,
    label: str = "模板",
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
    last_report = 0.0
    logged_shape = False

    while time.time() < deadline:
        image, offset = _capture_with_roi(region, roi_region, window_title)
        img_height, img_width = image.shape[:2]
        tpl_height, tpl_width = template.shape[:2]
        if img_height < tpl_height or img_width < tpl_width:
            if not logged_size_mismatch:
                logger.error(
                    "%s截图区域小于模板尺寸，无法匹配: image=%dx%d, template=%dx%d，继续等待",
                    label,
                    img_width,
                    img_height,
                    tpl_width,
                    tpl_height,
                )
                logged_size_mismatch = True
            time.sleep(poll_interval)
            continue
        if not logged_shape:
            logger.info(
                "%s检测参数: roi=%s, image=%dx%d, template=%dx%d, threshold=%.3f",
                label,
                roi_region,
                img_width,
                img_height,
                tpl_width,
                tpl_height,
                threshold,
            )
            logged_shape = True

        result = match_template(
            image=image,
            template=template,
            threshold=threshold,
            offset=offset,
        )
        now = time.time()
        if now - last_report >= max(5.0, poll_interval):
            logger.info("%s模板匹配中: score=%.3f", label, result.score)
            last_report = now
        logger.debug("%s模板匹配得分=%.3f", label, result.score)
        if result.found:
            logger.info("检测到%s模板匹配成功，score=%.3f", label, result.score)
            return True

        time.sleep(poll_interval)

    logger.warning("等待%s超时", label)
    return False


def match_template_in_roi(
    template_path: Path,
    roi_path: Path,
    roi_name: str,
    window_title: str,
    threshold: float,
    label: str = "模板",
) -> MatchResult:
    template = _load_template(template_path)
    roi_region = load_roi_region(roi_path, roi_name)
    image, offset = _capture_with_roi(None, roi_region, window_title)
    img_height, img_width = image.shape[:2]
    tpl_height, tpl_width = template.shape[:2]
    if img_height < tpl_height or img_width < tpl_width:
        logger.error(
            "%s截图区域小于模板尺寸，无法匹配: image=%dx%d, template=%dx%d",
            label,
            img_width,
            img_height,
            tpl_width,
            tpl_height,
        )
        return MatchResult(found=False, score=0.0, center=None)
    result = match_template(
        image=image,
        template=template,
        threshold=threshold,
        offset=offset,
    )
    logger.debug("%s模板匹配得分=%.3f", label, result.score)
    return result


def match_template_in_region(
    template_path: Path,
    roi_region: tuple[int, int, int, int],
    window_title: str,
    threshold: float,
    label: str = "模板",
) -> MatchResult:
    template = _load_template(template_path)
    image, offset = _capture_with_roi(None, roi_region, window_title)
    img_height, img_width = image.shape[:2]
    tpl_height, tpl_width = template.shape[:2]
    if img_height < tpl_height or img_width < tpl_width:
        logger.error(
            "%s截图区域小于模板尺寸，无法匹配: image=%dx%d, template=%dx%d",
            label,
            img_width,
            img_height,
            tpl_width,
            tpl_height,
        )
        return MatchResult(found=False, score=0.0, center=None)
    return match_template(
        image=image,
        template=template,
        threshold=threshold,
        offset=offset,
    )


def _load_template(template_path: Path) -> np.ndarray:
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise FileNotFoundError(f"模板文件不存在或无法读取: {template_path}")
    return template


def load_roi_region(roi_path: Path, roi_name: str) -> tuple[int, int, int, int]:
    roi_data = _load_roi_json(roi_path)
    roi = _find_roi(roi_data.get("rois", []), roi_name)

    x = int(math.floor(roi["x"]))
    y = int(math.floor(roi["y"]))
    # 为避免浮点舍入导致 ROI 变小，宽高向上取整
    width = int(math.ceil(roi["w"]))
    height = int(math.ceil(roi["h"]))
    return (x, y, width, height)


def list_roi_names(roi_path: Path) -> list[str]:
    roi_data = _load_roi_json(roi_path)
    names: list[str] = []
    for roi in roi_data.get("rois", []):
        name = roi.get("name")
        if name:
            names.append(str(name))
    return names


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

    foreground = win32gui.GetForegroundWindow()
    if foreground and title_keyword in win32gui.GetWindowText(foreground):
        left, top, right, bottom = win32gui.GetWindowRect(foreground)
        return (left, top, right - left, bottom - top)

    matches: list[tuple[int, int, int, int]] = []

    def _enum_handler(hwnd: int, extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if title_keyword in title:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            matches.append((left, top, right, bottom))

    win32gui.EnumWindows(_enum_handler, None)
    if not matches:
        raise ValueError(f"未找到窗口: {title_keyword}")

    left, top, right, bottom = matches[0]
    return (left, top, right - left, bottom - top)


def click_point(point: tuple[int, int], clicks: int = 1, interval: float = 0.1) -> None:
    if clicks <= 0:
        raise ValueError("clicks 必须大于 0")
    if interval < 0:
        raise ValueError("interval 不能小于 0")

    if _send_input_click(point, clicks, interval):
        return

    import pyautogui

    pyautogui.click(point[0], point[1], clicks=clicks, interval=interval)


def press_key(key: str) -> None:
    import pyautogui

    pyautogui.press(key)


def _send_input_click(
    point: tuple[int, int],
    clicks: int,
    interval: float,
) -> bool:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    screen_width = user32.GetSystemMetrics(0)
    screen_height = user32.GetSystemMetrics(1)
    if screen_width <= 1 or screen_height <= 1:
        logger.warning("屏幕尺寸异常，无法使用 SendInput")
        return False

    ulong_ptr = getattr(wintypes, "ULONG_PTR", ctypes.c_size_t)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ulong_ptr),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [
            ("type", wintypes.DWORD),
            ("mi", MOUSEINPUT),
        ]

    def _send(flags: int, dx: int, dy: int) -> bool:
        inp = INPUT(0, MOUSEINPUT(dx, dy, 0, flags, 0, 0))
        sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        if sent == 0:
            logger.warning(
                "SendInput 失败: flags=%s, err=%s",
                flags,
                ctypes.get_last_error(),
            )
            return False
        return True

    abs_x = int(point[0] * 65535 / (screen_width - 1))
    abs_y = int(point[1] * 65535 / (screen_height - 1))
    move_flags = 0x0001 | 0x8000
    down_flags = 0x0002 | 0x8000
    up_flags = 0x0004 | 0x8000

    if not _send(move_flags, abs_x, abs_y):
        return False

    press_delay = 0.02
    for index in range(clicks):
        if not _send(down_flags, abs_x, abs_y):
            return False
        time.sleep(press_delay)
        if not _send(up_flags, abs_x, abs_y):
            return False
        if index + 1 < clicks:
            time.sleep(interval)
    return True
