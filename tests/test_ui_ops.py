from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from src.ui_ops import BlueDominanceRule, is_blue_dominant, load_roi_region


def test_is_blue_dominant_true() -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    image[:, :, 0] = 180
    image[:, :, 1] = 60
    image[:, :, 2] = 60

    rule = BlueDominanceRule(min_blue=120, dominance=20)
    assert is_blue_dominant(image, rule) is True


def test_is_blue_dominant_false() -> None:
    image = np.zeros((10, 10, 3), dtype=np.uint8)
    image[:, :, 0] = 80
    image[:, :, 1] = 80
    image[:, :, 2] = 80

    rule = BlueDominanceRule(min_blue=120, dominance=20)
    assert is_blue_dominant(image, rule) is False


def test_load_roi_region_with_window_rect(tmp_path: Path) -> None:
    roi_path = tmp_path / "roi.json"
    roi_data = {
        "window": {"rect": [100, 200, 300, 400]},
        "rois": [
            {
                "name": "button",
                "x": 10.2,
                "y": 20.7,
                "w": 88.5,
                "h": 35.1,
            }
        ],
    }
    roi_path.write_text(json.dumps(roi_data), encoding="utf-8")

    region = load_roi_region(roi_path, "button")
    assert region == (10, 21, 88, 35)
