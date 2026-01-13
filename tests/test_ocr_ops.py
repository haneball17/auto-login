from __future__ import annotations

from src.ocr_ops import OcrItem, find_keyword_items


def test_find_keyword_items_filters_by_score() -> None:
    items = [
        OcrItem(text="确认", score=0.4, box=None, bbox=None),
        OcrItem(text="确认", score=0.8, box=None, bbox=None),
        OcrItem(text="取消", score=0.9, box=None, bbox=None),
    ]

    matched = find_keyword_items(items, ["确认"], min_score=0.5)
    assert len(matched) == 1
    assert matched[0].text == "确认"
    assert matched[0].score == 0.8


def test_find_keyword_items_empty_when_no_keywords() -> None:
    items = [
        OcrItem(text="确认", score=0.9, box=None, bbox=None),
    ]
    matched = find_keyword_items(items, [], min_score=0.5)
    assert matched == []
