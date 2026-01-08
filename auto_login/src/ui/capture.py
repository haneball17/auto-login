from __future__ import annotations

from typing import Iterable

try:
    import cv2
    import numpy as np
    import pyautogui
except ModuleNotFoundError as exc:  # pragma: no cover - 运行时依赖
    raise RuntimeError(
        "缺少 UI 依赖库，请先安装：pip install opencv-python pyautogui"
    ) from exc


def capture_screen(region: Iterable[int] | None = None) -> "np.ndarray":
    """
    截取屏幕画面并返回 OpenCV 可用的 BGR 图像。

    region: 可选的区域 (left, top, width, height)，用于加速匹配。
    """

    screenshot = pyautogui.screenshot(region=tuple(region) if region else None)
    image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
    return image
