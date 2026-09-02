"""Shingle fingerprints for Gate 3 (the Original check, spec §10.3).

Resolves the spec contradiction: voice profiles must never store full
article text, but the Original gate needs *something* of the broker's own
published prose to compare a draft against. `shingle_hashes` reduces text to
a set of opaque integers (overlapping n-word sequences, hashed) -- nothing
here is invertible back to prose.
"""
from bce.fingerprint import SHINGLE_SIZE, containment, shingle_hashes


def test_shingle_size_is_six_words():
    """n=6: within the 5-8 word range standard for near-duplicate shingling
    -- long enough that a 6-word run recurring is a genuine signal rather
    than common phrasing, short enough that even a SHORT_MIN_WORDS=100-word
    newsletter blurb still yields plenty of shingles to compare.
    """
    assert SHINGLE_SIZE == 6


def test_identical_text_yields_identical_hashes():
    text = "The quick brown fox jumps over the lazy dog again today"
    assert shingle_hashes(text) == shingle_hashes(text)


def test_hashes_are_plain_ints_not_recoverable_text():
    text = "The quick brown fox jumps over the lazy dog again today"
    hashes = shingle_hashes(text)
    assert hashes
    assert all(isinstance(h, int) for h in hashes)


def test_short_text_below_shingle_size_yields_no_shingles():
    assert shingle_hashes("too short") == set()
    assert shingle_hashes("") == set()
    assert shingle_hashes(None) == set()


def test_shingle_count_matches_word_count_minus_n_plus_one():
    # 10 distinct words, n=6 -> 10 - 6 + 1 = 5 overlapping shingles.
    text = "one two three four five six seven eight nine ten"
    assert len(shingle_hashes(text)) == 5


def test_different_text_yields_different_hashes():
    a = shingle_hashes("The quick brown fox jumps over the lazy dog today")
    b = shingle_hashes("Sunreef catamarans offer bluewater comfort for owners now")
    assert a.isdisjoint(b)


def test_case_and_whitespace_insensitive():
    a = shingle_hashes("The Quick Brown Fox Jumps Over The Lazy Dog")
    b = shingle_hashes("the   quick brown fox jumps over the lazy dog")
    assert a == b


# --- containment ------------------------------------------------------------


def test_containment_of_fully_overlapping_sets_is_one():
    draft = {1, 2, 3}
    source = {1, 2, 3, 4, 5}
    assert containment(draft, source) == 1.0


def test_containment_of_disjoint_sets_is_zero():
    assert containment({1, 2, 3}, {4, 5, 6}) == 0.0


def test_containment_is_fraction_of_draft_found_in_source():
    # 2 of the draft's 4 shingles are in source -> 0.5.
    assert containment({1, 2, 3, 4}, {1, 2, 9, 10}) == 0.5


def test_containment_of_empty_draft_is_zero_not_a_division_error():
    assert containment(set(), {1, 2, 3}) == 0.0


def test_containment_against_empty_source_is_zero():
    assert containment({1, 2, 3}, set()) == 0.0


def test_containment_is_asymmetric_unlike_jaccard():
    """A small draft fully contained in a huge source scores 1.0 -- the
    whole point of containment over Jaccard, which would be crushed toward
    zero by the size mismatch between one draft and a broker's entire
    published corpus.
    """
    draft = {1, 2}
    huge_source = set(range(1, 1000))
    assert containment(draft, huge_source) == 1.0
