from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import ScheduleConfig


def test_fixed_time_gap_too_small() -> None:
    with pytest.raises(ValidationError):
        ScheduleConfig.model_validate(
            {
                "mode": "fixed_times",
                "min_gap_minutes": 90,
                "fixed_times": ["07:00", "08:00"],
            }
        )


def test_random_window_count() -> None:
    with pytest.raises(ValidationError):
        ScheduleConfig.model_validate(
            {
                "mode": "random_window",
                "min_gap_minutes": 90,
                "random_windows": [
                    {"center": "07:00", "jitter_minutes": 3}
                ],
            }
        )
