from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from .ui_ops import capture_window

logger = logging.getLogger("auto_login")

_OCR_INSTANCE = None


@dataclass(frozen=True)
class OcrItem:
    text: str
    score: float | None
    box: list[tuple[float, float]] | None
    bbox: tuple[int, int, int, int] | None

    def center(self) -> tuple[int, int] | None:
        if self.bbox is None:
            return None
        left, top, right, bottom = self.bbox
        center_x = int((left + right) / 2)
        center_y = int((top + bottom) / 2)
        return (center_x, center_y)


def get_ocr():
    global _OCR_INSTANCE
    if _OCR_INSTANCE is False:
        return None
    if _OCR_INSTANCE is None:
        try:
            from cnocr import CnOcr
        except ImportError as exc:
            try:
                from cnocr import CnOCR as CnOcr
            except ImportError as nested_exc:
                logger.warning(
                    "OCR 初始化失败: %s",
                    nested_exc,
                )
                _OCR_INSTANCE = False
                return None
        try:
            _OCR_INSTANCE = CnOcr()
        except Exception as exc:
            logger.warning("OCR 初始化失败: %s", exc)
            _OCR_INSTANCE = False
            return None
    return _OCR_INSTANCE


def ocr_window_items(
    window_title: str,
    region_ratio: float,
) -> list[OcrItem]:
    try:
        image, rect = capture_window(window_title)
    except Exception as exc:
        logger.warning("OCR 截图失败: %s", exc)
        return []

    region, offset = _crop_center_region(image, region_ratio)
    rgb = cv2.cvtColor(region, cv2.COLOR_BGR2RGB)
    try:
        ocr = get_ocr()
    except Exception as exc:
        logger.warning("OCR 初始化失败: %s", exc)
        return []
    if ocr is None:
        return []
    try:
        results = ocr.ocr(rgb)
    except Exception as exc:
        logger.warning("OCR 识别失败: %s", exc)
        return []
    screen_offset = (rect[0] + offset[0], rect[1] + offset[1])
    return _parse_ocr_results(results, screen_offset)


def ocr_window_text(
    window_title: str,
    region_ratio: float,
) -> str:
    items = ocr_window_items(window_title, region_ratio)
    texts = [item.text for item in items if item.text]
    return "".join(texts)


def contains_keywords(text: str, keywords: list[str]) -> bool:
    if not text:
        return False
    return any(keyword in text for keyword in keywords)


def find_keyword_items(
    items: list[OcrItem],
    keywords: list[str],
    min_score: float,
) -> list[OcrItem]:
    if not items or not keywords:
        return []
    matched: list[OcrItem] = []
    for item in items:
        if not item.text:
            continue
        if not any(keyword in item.text for keyword in keywords):
            continue
        score = item.score if item.score is not None else 1.0
        if score < min_score:
            continue
        matched.append(item)
    return matched


def _crop_center_region(
    image: np.ndarray,
    ratio: float,
) -> tuple[np.ndarray, tuple[int, int]]:
    height, width = image.shape[:2]
    ratio = max(0.1, min(ratio, 1.0))
    region_w = int(width * ratio)
    region_h = int(height * ratio)
    left = max(0, (width - region_w) // 2)
    top = max(0, (height - region_h) // 2)
    right = min(width, left + region_w)
    bottom = min(height, top + region_h)
    return image[top:bottom, left:right], (left, top)


def _parse_ocr_results(
    results,
    offset: tuple[int, int],
) -> list[OcrItem]:
    items: list[OcrItem] = []
    for raw in results or []:
        parsed = _parse_single_item(raw, offset)
        if parsed is not None and parsed.text:
            items.append(parsed)
    return items


def _parse_single_item(
    raw,
    offset: tuple[int, int],
) -> OcrItem | None:
    text = None
    score = None
    box = None

    if isinstance(raw, dict):
        # 兼容不同 OCR 输出字段命名
        text = raw.get("text") or raw.get("transcription") or raw.get("value")
        score = raw.get("score") or raw.get("prob") or raw.get("confidence")
        box = (
            raw.get("position")
            or raw.get("points")
            or raw.get("box")
            or raw.get("bbox")
            or raw.get("polygon")
        )
    elif isinstance(raw, (list, tuple)):
        if raw:
            if isinstance(raw[0], str):
                # 常见结构: [text, score, box]
                text = raw[0]
                if len(raw) > 1 and isinstance(raw[1], (int, float)):
                    score = raw[1]
                if len(raw) > 2:
                    box = raw[2]
            elif len(raw) >= 2 and isinstance(raw[0], (list, tuple)):
                # 兼容嵌套结构: [(text, score), points]
                if isinstance(raw[0][0], str):
                    text = raw[0][0]
                if len(raw[0]) > 1 and isinstance(raw[0][1], (int, float)):
                    score = raw[0][1]
                box = raw[1]

    if text is None:
        return None
    text = str(text)
    if score is not None:
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = None
    normalized_box = _normalize_box(box, offset)
    bbox = _box_to_bbox(normalized_box)
    return OcrItem(
        text=text,
        score=score,
        box=normalized_box,
        bbox=bbox,
    )


def _normalize_box(
    box,
    offset: tuple[int, int],
) -> list[tuple[float, float]] | None:
    if box is None:
        return None
    points: list[tuple[float, float]] = []
    if isinstance(box, np.ndarray):
        box = box.tolist()
    if isinstance(box, (list, tuple)):
        if len(box) == 4 and all(isinstance(v, (int, float)) for v in box):
            # 兼容 [x1, y1, x2, y2] 形式
            x1, y1, x2, y2 = box
            points = [
                (float(x1), float(y1)),
                (float(x2), float(y1)),
                (float(x2), float(y2)),
                (float(x1), float(y2)),
            ]
        elif box and isinstance(box[0], (list, tuple)):
            for point in box:
                if len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
    if not points:
        return None
    offset_x, offset_y = offset
    return [
        (x + offset_x, y + offset_y)
        for x, y in points
    ]


def _box_to_bbox(
    box: list[tuple[float, float]] | None,
) -> tuple[int, int, int, int] | None:
    if not box:
        return None
    xs = [point[0] for point in box]
    ys = [point[1] for point in box]
    left = int(min(xs))
    top = int(min(ys))
    right = int(max(xs))
    bottom = int(max(ys))
    return (left, top, right, bottom)
