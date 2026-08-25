import json

import pytest
from bce.style import avg_sentence_length, structure_pattern, typical_word_count


def _shape(texts):
    """structure_pattern parsed back (I7: it stores JSON, like its siblings)."""
    return json.loads(structure_pattern(texts))


def test_avg_sentence_length_counts_words_per_sentence():
    # 2 sentences, 4 + 6 = 10 words -> 5.0
    assert avg_sentence_length(["One two three four. Five six seven eight nine ten."]) == 5.0


def test_avg_sentence_length_ignores_decimals_and_abbreviations():
    # One sentence. "24.5" and "approx." must not split it.
    text = "She measures approx. 24.5 m and sleeps eight guests in four cabins."
    assert avg_sentence_length([text]) == pytest.approx(13.0)


def test_avg_sentence_length_handles_no_input():
    assert avg_sentence_length([]) == 0.0
    assert avg_sentence_length([""]) == 0.0


def test_typical_word_count_is_the_median():
    assert typical_word_count(["a b", "a b c d", "a b c d e f"]) == 4


def test_typical_word_count_rounds_fractional_median():
    # Even-length list: median of [2, 5] is 3.5, should round to 4
    assert typical_word_count(["a b", "a b c d e"]) == 4


def test_typical_word_count_handles_no_input():
    assert typical_word_count([]) == 0


def test_structure_pattern_reports_paragraphs_and_density():
    text = "First para here.\n\nSecond para here.\n\nThird para here."
    assert _shape([text]) == {"paragraphs_per_article": 3, "words_per_paragraph": 3}


def test_structure_pattern_stores_json_so_stage_4_can_score_structure():
    """I7: siblings in the same INSERT store JSON; §10.3 needs numbers, not prose."""
    raw = structure_pattern(["First para here.\n\nSecond para here."])
    parsed = json.loads(raw)  # must not raise
    assert isinstance(parsed["paragraphs_per_article"], int)
    assert isinstance(parsed["words_per_paragraph"], int)


def test_structure_pattern_computes_per_article_mean():
    # Three texts with 2, 3, 4 paragraphs respectively (mean 3)
    texts = [
        "A.\n\nB.",  # 2 paragraphs, 1 word each
        "X.\n\nY.\n\nZ.",  # 3 paragraphs, 1 word each
        "P.\n\nQ.\n\nR.\n\nS.",  # 4 paragraphs, 1 word each
    ]
    assert _shape(texts) == {"paragraphs_per_article": 3, "words_per_paragraph": 1}


def test_structure_pattern_rounds_fractional_mean():
    # Two texts with 3 and 4 paragraphs: mean = 3.5 → round(3.5) = 4
    # (Python banker's rounding: round-half-to-even). Rounding stays at compute
    # time so every reader of the column sees the same integer.
    texts = [
        "A.\n\nB.\n\nC.",  # 3 paragraphs, 1 word each
        "X.\n\nY.\n\nZ.\n\nW.",  # 4 paragraphs, 1 word each
    ]
    assert _shape(texts) == {"paragraphs_per_article": 4, "words_per_paragraph": 1}


def test_structure_pattern_skips_empty_texts():
    # Mixed list: one normal text and one empty string
    texts = [
        "First.\n\nSecond.",  # 2 paragraphs, 1 word each
        "",  # Empty, should be skipped
    ]
    assert _shape(texts) == {"paragraphs_per_article": 2, "words_per_paragraph": 1}


def test_structure_pattern_handles_no_input():
    """No-input stays parseable JSON, distinguishable from real data by nulls."""
    assert _shape([]) == {
        "paragraphs_per_article": None,
        "words_per_paragraph": None,
    }


def test_structure_pattern_ignores_blank_runs():
    text = "One two.\n\n\n\nThree four."
    assert _shape([text]) == {"paragraphs_per_article": 2, "words_per_paragraph": 2}


@pytest.mark.parametrize(
    "text,expected_sentence_count",
    [
        # Decimal: $1.5m should not split (period not followed by capital after space)
        ("Asking $1.5m. She is ready.", 2),
        # Abbreviation: e.g. should not split (followed by lowercase)
        ("Delivery e.g. next spring is typical.", 1),
        # Abbreviation: 60 ft. should split (followed by capital after space)
        ("She is 60 ft. Built in 2019.", 2),
    ],
)
def test_avg_sentence_length_sentence_splitting_edge_cases(text, expected_sentence_count):
    # These test the _SENTENCE_END regex behavior on real yacht-industry phrases
    from bce.style import _sentences
    sentences = _sentences(text)
    assert len(sentences) == expected_sentence_count
