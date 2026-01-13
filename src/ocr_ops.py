from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from .ui_ops import capture_window

logger = logging.getLogger("auto_login")

_OCR_INSTANCE = None


def get_ocr():
    global _OCR_INSTANCE
    if _OCR_INSTANCE is None:
        try:
            from cnocr import CnOCR
        except ImportError as exc:
            raise RuntimeError("CnOCR 未安装，请先安装 cnocr") from exc
        _OCR_INSTANCE = CnOCR()
    return _OCR_INSTANCE


def ocr_window_text(
    window_title: str,
    region_ratio: float,
) -> str:
    try:
        image, _ = capture_window(window_title)
    except Exception as exc:
        logger.warning("OCR 截图失败: %s", exc)
        return ""

    region = _crop_center_region(image, region_ratio)
    rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
    ocr = get_ocr()
    results = ocr.ocr(rgb)
    return _flatten_ocr_results(results)


def contains_keywords(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in keywords)


def _crop_center_region(image: np.ndarray, ratio: float) -> np.ndarray:
    height, width = image.shape[:2]
    ratio = max(0.1, min(ratio, 1.0))
    region_w = int(width * ratio)
    region_h = int(height * ratio)
    left = max(0, (width - region_w) // 2)
    top = max(0, (height - region_h) // 2)
    right = min(width, left + region_w)
    bottom = min(height, top + region_h)
    return image[top:bottom, left:right]


def _flatten_ocr_results(results) -> str:
    texts: list[str] = []
    for item in results or []:
        if isinstance(item, dict):
            text = item.get("text")
            if text:
                texts.append(str(text))
        elif isinstance(item, (list, tuple)):
            if item:
                texts.append(str(item[0]))
    return "".join(texts)
