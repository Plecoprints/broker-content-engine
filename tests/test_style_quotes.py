from bce.style import MAX_QUOTE_CHARS, MAX_QUOTES, select_quotes


def test_selects_at_most_max_quotes():
    text = " ".join(f"Sentence number {i} here about boats." for i in range(30))
    assert len(select_quotes([text])) <= MAX_QUOTES


def test_every_quote_is_capped():
    long_sentence = "A " + "very " * 300 + "long sentence."
    for quote in select_quotes([long_sentence]):
        assert len(quote) <= MAX_QUOTE_CHARS


def test_no_quote_reproduces_a_long_verbatim_run():
    """Spec section 10.3 — features and short quotes only, never the article."""
    article = " ".join(f"This is sentence {i} of a real article." for i in range(80))
    quotes = select_quotes([article])
    stored = " ".join(quotes)
    assert len(stored) <= MAX_QUOTES * MAX_QUOTE_CHARS
    assert len(stored) < len(article) / 4


def test_handles_no_input():
    assert select_quotes([]) == []
    assert select_quotes([""]) == []


def test_prefers_sentences_near_the_mean_length():
    """Assert that sentences closest to the mean length are preferred.

    This test creates a fixture with:
    - One very short sentence (1 word) - clear outlier
    - One very long sentence (50 words) - clear outlier
    - Six moderate-length sentences (5-8 words each) - near the mean
    - Total of 8 sentences, so MAX_QUOTES=5 forces selection

    With ranking by proximity to mean, the 5 moderate sentences should be
    selected, excluding the outliers.

    Without ranking (just taking first N), the short outlier would be included
    in the top 5, causing this test to fail.
    """
    # Build fixture: Short (1 word), then 6 moderate (5-8 words each),
    # then Long (50 words) at the end
    texts = [
        "Short. " +
        "First moderate sentence goes here. " +
        "Second moderate sentence also present. " +
        "Third moderate one for good measure. " +
        "Fourth moderate sentence appears now. " +
        "Fifth moderate sentence shows up. " +
        "Sixth moderate sentence completes the set. " +
        "Word " * 50 + "long."
    ]
    quotes = select_quotes(texts)

    # Should have returned exactly MAX_QUOTES sentences
    assert len(quotes) == MAX_QUOTES

    # The "Short" sentence (1 word) should NOT be in the results, as it's
    # a clear outlier far below the mean. With 8 sentences and MAX_QUOTES=5,
    # and mean ~8 words, the ranking should select the 5 closest to mean,
    # which excludes the 1-word and 50-word outliers.
    short_in_quotes = any("Short" in q for q in quotes)
    assert not short_in_quotes, "Short outlier should not be selected when 6 moderate sentences available"


def test_length_cap_truncates_individual_quotes():
    """Verify the length cap (MAX_QUOTE_CHARS) actually truncates long sentences.

    This test ensures that even if we select only a few sentences, each one is
    individually capped at MAX_QUOTE_CHARS. The count cap (MAX_QUOTES) would be
    satisfied with fewer sentences, but the length cap still applies per-quote.
    """
    # Create a few sentences, one of which is very long (>200 chars)
    # The long one should be truncated
    long_sentence = "Very " * 50 + "long sentence."  # ~315 chars
    medium_sentence = "This is a medium sentence with some text in it."

    texts = [long_sentence, medium_sentence]
    quotes = select_quotes(texts)

    # Every quote must be <= MAX_QUOTE_CHARS
    for quote in quotes:
        assert len(quote) <= MAX_QUOTE_CHARS

    # The long sentence, if selected, should be truncated
    if any("Very" in q for q in quotes):
        # The long sentence was selected
        long_quote = [q for q in quotes if "Very" in q][0]
        assert len(long_quote) <= MAX_QUOTE_CHARS
        # Verify it was actually truncated (not the full sentence)
        assert len(long_quote) < len(long_sentence)
