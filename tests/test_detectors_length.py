import pytest
from bce.detectors import detect_max_length_ft


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
])
def test_detect_max_length_ft(text, expected):
    assert detect_max_length_ft(text) == expected


def test_prefers_largest_when_mixed_units():
    # 30m = 98ft beats the 60ft mention
    assert detect_max_length_ft("60 ft tender aboard a 30 m yacht") == 98
