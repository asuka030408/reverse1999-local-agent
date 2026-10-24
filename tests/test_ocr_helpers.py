from reverse1999_agent.vision import OcrItem, deficient_ratios


def test_deficient_ratios_only_returns_shortages() -> None:
    items = [
        OcrItem(text="1/3", confidence=1, center_x=1, center_y=1),
        OcrItem(text="16/6", confidence=1, center_x=2, center_y=2),
        OcrItem(text="30/30", confidence=1, center_x=3, center_y=3),
        OcrItem(text="/3", confidence=1, center_x=4, center_y=4),
    ]
    shortages = deficient_ratios(items)
    assert [(available, required) for _, available, required in shortages] == [(1, 3), (0, 3)]
