from __future__ import annotations

import numpy as np

from src.ui_ops import BlueDominanceRule, is_blue_dominant


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
