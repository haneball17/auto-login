from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
import pyautogui

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


def capture_screen(region: tuple[int, int, int, int] | None = None) -> np.ndarray:
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

    return blue - max(green, red) >= rule.dominance


def wait_launcher_start_enabled(
    template_path: Path,
    region: tuple[int, int, int, int] | None,
    timeout_seconds: int = 60,
    threshold: float = 0.86,
    poll_interval: float = 1.0,
    color_rule: BlueDominanceRule | None = None,
) -> bool:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds 必须大于 0")
    if poll_interval <= 0:
        raise ValueError("poll_interval 必须大于 0")

    template = _load_template(template_path)
    deadline = time.time() + timeout_seconds

    while time.time() < deadline:
        image = capture_screen(region=region)

        if color_rule is not None and region is not None:
            if is_blue_dominant(image, color_rule):
                logger.info("检测到启动按钮变为可用颜色")
                return True

        result = match_template(
            image=image,
            template=template,
            threshold=threshold,
            offset=(region[0], region[1]) if region else (0, 0),
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
