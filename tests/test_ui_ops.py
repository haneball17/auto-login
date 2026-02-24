from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.ui_ops import (
    BlueDominanceRule,
    compute_visible_ratio,
    intersect_rect,
    is_blue_dominant,
    is_point_in_rect,
    list_roi_names,
    load_roi_region,
    map_point_to_absolute,
)


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
    assert region == (10, 20, 89, 36)


def test_list_roi_names(tmp_path: Path) -> None:
    roi_path = tmp_path / "roi.json"
    roi_data = {
        "rois": [
            {"name": "channel_1", "x": 0, "y": 0, "w": 1, "h": 1},
            {"name": "channel_2", "x": 0, "y": 0, "w": 1, "h": 1},
            {"name": "", "x": 0, "y": 0, "w": 1, "h": 1},
        ]
    }
    roi_path.write_text(json.dumps(roi_data), encoding="utf-8")

    names = list_roi_names(roi_path)
    assert names == ["channel_1", "channel_2"]


def test_intersect_rect_partial_overlap() -> None:
    first = (0, 0, 100, 100)
    second = (50, 30, 80, 50)
    assert intersect_rect(first, second) == (50, 30, 50, 50)


def test_compute_visible_ratio_partial() -> None:
    window_rect = (-200, 0, 1000, 800)
    visible_rect = (0, 0, 1920, 1080)
    ratio = compute_visible_ratio(window_rect, visible_rect)
    assert ratio == pytest.approx(0.8)


def test_map_point_to_absolute_supports_virtual_desktop() -> None:
    virtual_rect = (-1920, 0, 3840, 1080)
    point = (0, 540)
    abs_x, abs_y = map_point_to_absolute(point, virtual_rect)
    assert 32000 <= abs_x <= 33500
    assert 32700 <= abs_y <= 32850


def test_map_point_to_absolute_rejects_outside_point() -> None:
    virtual_rect = (0, 0, 1920, 1080)
    assert is_point_in_rect((1919, 1079), virtual_rect) is True
    with pytest.raises(ValueError):
        map_point_to_absolute((2500, 500), virtual_rect)
