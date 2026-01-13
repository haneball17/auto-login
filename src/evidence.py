from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime
from pathlib import Path

import cv2

from .ocr_ops import ocr_window_text
from .ui_ops import capture_screen, capture_window

logger = logging.getLogger("auto_login")


def save_ui_evidence(
    evidence_dir: Path | None,
    tag: str,
    window_title: str | None,
    error: Exception | str | None = None,
    extra: dict | None = None,
    ocr_region_ratio: float | None = None,
) -> Path | None:
    if evidence_dir is None:
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = evidence_dir / f"{tag}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    screenshot_path = output_dir / "screenshot.png"
    context_path = output_dir / "context.json"
    ocr_path = output_dir / "ocr.txt"
    error_path = output_dir / "error.txt"

    image = None
    try:
        if window_title:
            image, _ = capture_window(window_title)
        else:
            image = capture_screen()
    except Exception as exc:
        logger.warning("证据截图失败: %s", exc)
        try:
            image = capture_screen()
        except Exception as nested:
            logger.warning("证据全屏截图失败: %s", nested)
    if image is not None:
        try:
            cv2.imwrite(str(screenshot_path), image)
        except Exception as exc:
            logger.warning("证据截图写入失败: %s", exc)

    ocr_text = ""
    if window_title and ocr_region_ratio is not None:
        try:
            ocr_text = ocr_window_text(window_title, ocr_region_ratio)
        except Exception as exc:
            logger.warning("证据 OCR 获取失败: %s", exc)
    if ocr_text:
        ocr_path.write_text(ocr_text, encoding="utf-8")

    context = {
        "tag": tag,
        "timestamp": timestamp,
        "window_title": window_title,
        "extra": extra or {},
    }
    context_path.write_text(
        json.dumps(context, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if error is not None:
        if isinstance(error, Exception):
            error_text = "".join(
                traceback.format_exception(
                    type(error),
                    error,
                    error.__traceback__,
                )
            )
        else:
            error_text = str(error)
        error_path.write_text(error_text, encoding="utf-8")

    return output_dir
