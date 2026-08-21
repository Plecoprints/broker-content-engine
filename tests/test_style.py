import pytest
from bce.style import avg_sentence_length, structure_pattern, typical_word_count


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


def test_typical_word_count_handles_no_input():
    assert typical_word_count([]) == 0


def test_structure_pattern_reports_paragraphs_and_density():
    text = "First para here.\n\nSecond para here.\n\nThird para here."
    assert structure_pattern([text]) == "3 paragraphs, 3 words/para"


def test_structure_pattern_handles_no_input():
    assert structure_pattern([]) == "unknown"


def test_structure_pattern_ignores_blank_runs():
    text = "One two.\n\n\n\nThree four."
    assert structure_pattern([text]) == "2 paragraphs, 2 words/para"
