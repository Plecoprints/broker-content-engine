import pytest
from bce.detectors import detect_max_length_ft, visible_text


@pytest.mark.parametrize("text,expected", [
    ("Sunreef 80 Eco, 80 ft of luxury", 80),
    ("A 72ft catamaran", 72),
    ("Length overall: 68'", 68),
    ("24 m sailing catamaran", 79),          # 24 * 3.28084 = 78.7 -> 79
    ("22 meters of deck space", 72),
    ("Our fleet ranges from 45 ft to 90 ft", 90),
    ("no numbers here", None),
    ("Built in 1998, price 1200000", None),  # year/price must not match
    ("A 12 ft dinghy", None),                # below 20ft floor
    ("A 500 ft ship", None),                 # above 400ft ceiling
    ("Asking $25m for this vessel", None),   # currency symbol prevents match
    ("Priced at £10m", None),                # currency symbol prevents match
    ("12345ft", None),                       # long digit run prevents match
    ("30 m yacht", 98),                      # regression: bare m with space still works
])
def test_detect_max_length_ft(text, expected):
    assert detect_max_length_ft(text) == expected


def test_prefers_largest_when_mixed_units():
    # 30m = 98ft beats the 60ft mention
    assert detect_max_length_ft("60 ft tender aboard a 30 m yacht") == 98


# --- C1: the detector is written for extracted text, not raw markup ----------

RAW_HTML = (
    "<html lang='en'><head><style>.m-b-30{margin:0}</style>"
    "<script>var carousel={width:'150',speed:'300'};</script></head>"
    "<body><img width='150' height='80' src='/x.png'>"
    "<p>Catamarans from 42' to 55'.</p></body></html>"
)


def test_visible_text_drops_markup_script_and_style():
    text = visible_text(RAW_HTML)
    assert "42'" in text and "55'" in text
    assert "150" not in text
    assert "carousel" not in text
    assert "margin" not in text
    assert "<" not in text


def test_length_from_visible_text_ignores_attribute_and_script_numbers():
    """Raw markup used to yield 300 (a script value) instead of 55."""
    assert detect_max_length_ft(RAW_HTML) == 300      # documents the trap
    assert detect_max_length_ft(visible_text(RAW_HTML)) == 55


def test_visible_text_tolerates_malformed_and_empty_input():
    assert visible_text("") == ""
    assert "hello" in visible_text("hello <div><p>world")
