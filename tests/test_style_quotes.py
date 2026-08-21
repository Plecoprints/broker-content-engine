from bce.style import MAX_QUOTE_CHARS, MAX_QUOTES, MAX_RETAINED_FRACTION, select_quotes


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
    - Multiple moderate-length sentences (~10 words each) - near the mean
    - Large source (~4000+ chars) so proportional cap doesn't limit results
    - More than MAX_QUOTES sentences to force ranking-based selection

    With ranking by proximity to mean, the moderate sentences should dominate
    while the short and long outliers should be excluded.

    Without ranking (just taking first N), the short outlier would be included.
    """
    # Build a large fixture: Short (1 word), then 20 moderate sentences,
    # then Long (50 words). Total source ~4000+ chars, 25% threshold ~1000 chars,
    # 5 quotes of ~50 chars each = 250 chars (well within limit).
    moderate_sentences = [
        f"Sentence number {i} with moderate word count and some content here. "
        for i in range(20)
    ]
    texts = [
        "Short. " +
        "".join(moderate_sentences) +
        "Word " * 50 + "long."
    ]
    quotes = select_quotes(texts)

    # Should have returned MAX_QUOTES sentences
    assert len(quotes) == MAX_QUOTES

    # The "Short" sentence (1 word) should NOT be in the results, as it's
    # a clear outlier far below the mean.
    short_in_quotes = any("Short" in q for q in quotes)
    assert not short_in_quotes, "Short outlier should not be selected when many moderate sentences available"


def test_length_cap_truncates_individual_quotes():
    """Verify the length cap (MAX_QUOTE_CHARS) actually truncates long sentences.

    This test ensures that each quote is individually capped at MAX_QUOTE_CHARS.
    """
    # Create a very long sentence (1500+ chars) and a large source so the proportional
    # cap doesn't reject it entirely. The source must be large: 1500 / 0.25 = 6000 chars.
    long_sentence = "A " + "very " * 300 + "long sentence."  # ~1500 chars, ~300 words
    padding = "Padding sentence. " * 100  # Add filler to reach ~6000 char source total

    texts = [padding + long_sentence]

    quotes = select_quotes(texts)

    # Must return at least one quote
    assert len(quotes) > 0

    # Every quote must respect the per-quote length cap
    for quote in quotes:
        assert len(quote) <= MAX_QUOTE_CHARS

    # Check if the very long sentence appears in the results. It may or may not,
    # depending on its distance from the mean. But IF it does, it must be truncated.
    long_quote_found = [q for q in quotes if "very" in q]
    if long_quote_found:
        long_quote = long_quote_found[0]
        # Verify it was truncated (not the full long sentence)
        assert len(long_quote) < len(long_sentence)


def test_proportional_cap_limits_retained_fraction():
    """Verify the proportional cap (MAX_RETAINED_FRACTION = 25%) enforces spec §10.3.

    Total retained characters must not exceed 25% of combined source length.
    With five ~400-char sentences and moderate word counts, this cap becomes binding.
    """
    # Create 5 sentences, each ~400 chars, with varying word counts so none are outliers
    # Total source: ~2000 chars, so 25% threshold is ~500 chars
    sentences = [
        "Sentence one. " * 25 + "end.",  # ~400 chars
        "Sentence two. " * 25 + "end.",  # ~400 chars
        "Sentence three. " * 25 + "end.",  # ~400 chars
        "Sentence four. " * 25 + "end.",  # ~400 chars
        "Sentence five. " * 25 + "end.",  # ~400 chars
    ]
    text = " ".join(sentences)
    quotes = select_quotes([text])

    # Calculate what was retained vs the 25% threshold
    source_length = len(text)
    stored = " ".join(quotes)
    retained_fraction = len(stored) / source_length if source_length > 0 else 0

    # The proportional cap should be enforced
    assert len(stored) <= int(source_length * MAX_RETAINED_FRACTION)
    assert retained_fraction <= MAX_RETAINED_FRACTION


def test_proportional_cap_rejects_oversized_single_quote():
    """Verify that a single quote exceeding the proportional limit is rejected entirely.

    If the source is so thin that even one truncated quote exceeds 25% of the
    source length, return empty list rather than storing an oversized excerpt.
    """
    # Create a source that is small enough that even a 200-char quote
    # exceeds 25% of the total. 200 / 0.25 = 800 chars max source.
    # So with a 600-char source, a 200-char quote = 33% (exceeds 25%).
    tiny_source = "Word " * 100  # ~500 chars
    quotes = select_quotes([tiny_source])

    # Should return empty list since any quote would be oversized
    assert quotes == []


def test_proportional_cap_realistic_case_still_returns_quotes():
    """Verify that the proportional cap doesn't fire on typical inputs.

    A normal article of ~5000 chars with 20 sentences of ordinary length
    should still return up to 5 quotes. The proportional cap should be
    generous on realistic input.
    """
    # 20 sentences of moderate length (~200-300 chars each)
    # Total ~5000+ chars, 25% threshold ~1250 chars
    # 5 quotes of 200 chars each = 1000 chars (well within budget)
    sentences = [
        f"This is sentence number {i} about a real topic with some detail and context. " * 2 + "Here."
        for i in range(20)
    ]
    text = " ".join(sentences)
    quotes = select_quotes([text])

    # Should return 5 quotes (MAX_QUOTES), not fewer
    assert len(quotes) == MAX_QUOTES

    # Verify they fit within the proportional cap
    stored = " ".join(quotes)
    assert len(stored) <= int(len(text) * MAX_RETAINED_FRACTION)
