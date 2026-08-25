import json

from bce import db, discover, profile, style

# Fixture corrections vs. the original task brief (verified by execution, not
# guesswork):
#
# 1. The brief's original single-paragraph ARTICLE extracted to 245 chars, giving
#    a MAX_RETAINED_FRACTION (25%) budget of ~61 chars -- too small for even one
#    single truncated (<=200 char) quote, so select_quotes returned []. This
#    fixture is a realistic 8-paragraph piece that extracts to 1642 chars (see
#    test_fixture_yields_quotes_and_a_discriminating_long_sentence below),
#    giving a ~410 char budget that comfortably admits real quotes.
#
# 2. The §10.3 guard needs a sentence that is actually selected by select_quotes'
#    "closest to mean word count" ranking AND is longer than MAX_QUOTE_CHARS
#    (200), so that removing the truncation would let it leak into storage in
#    full. LONG_SENTENCE below is 214 characters and is one of the two
#    sentences select_quotes actually picks for this fixture -- it is stored
#    truncated to 200 chars, so the *full* 214-char sentence is never present
#    in the row. If the 200-char cap were bypassed, the full sentence would
#    appear verbatim and the guard test below would fail.
ARTICLE = """<html><body><article>
<h1>Berthing in August</h1>
<p>Beam matters more than length when the marina is completely full during the
height of the Mediterranean season, and a wide platform buys deck space that
guests notice immediately upon arrival.</p>
<p>Draft is the constraint nobody mentions until it is too late in the season,
because the harbourmaster only checks keel depth after the deposit has already
been spent and the itinerary is fully confirmed and irreversible.</p>
<p>Fuel range gets discussed constantly during boat show conversations, though
it almost never actually decides a purchase once the discussion moves past the
printed brochure numbers and into real anchorage experience.</p>
<p>Galley layout wins or loses more sales than raw engine horsepower ever
could, because a guest who cannot see the water while cooking remembers that
particular discomfort for years afterward.</p>
<p>Owners ask about resale value before they ever ask about warranty coverage
terms, which tells you something genuinely important about how this
particular ownership market actually thinks about ten year horizons.</p>
<p>Charter operators obsess over turnaround time between departing and
arriving guest parties, and that single scheduling pressure quietly shapes the
entire interior floor plan long before construction even begins.</p>
<p>Shade on the flybridge sells considerably more boats during high summer
than any electronics package ever could, because guests remember discomfort
long after every specification has faded from memory.</p>
<p>Anchoring etiquette inside a crowded bay separates the seasoned charter
guest from the anxious newcomer faster than almost any other single moment
during an entire week aboard.</p>
</article></body></html>"""

# The one sentence in ARTICLE that is longer than MAX_QUOTE_CHARS (200) and is
# actually chosen by select_quotes' ranking, so it genuinely exercises the
# truncation cap rather than being excluded from selection for other reasons.
LONG_SENTENCE = (
    "Fuel range gets discussed constantly during boat show conversations, "
    "though it almost never actually decides a purchase once the discussion "
    "moves past the printed brochure numbers and into real anchorage "
    "experience"
)

HOME = '<html><body><a href="/blog">Blog</a> Our 80 ft fleet</body></html>'


# --- C1: the realistic two-level shape -------------------------------------
#
# The fixture above serves a complete article *at the editorial URL itself*,
# which is why the suite was green while Stage 3 was profiling index pages. Real
# brokers publish a homepage -> journal index -> posts. `find_editorial_urls`
# returns the index, and trafilatura on an index yields teaser fragments, so
# without a second hop the stored statistics describe the card layout.

HOME_2LEVEL = """<html><body>
  <nav>
    <a href="/journal">Journal</a>
    <a href="/news">News</a>
    <a href="/contact">Contact</a>
  </nav>
  <p>Our 80 ft fleet.</p>
</body></html>"""

# Teasers plus links to three posts, exactly as a journal index looks. Also
# carries nav links at the index's own depth, and an offsite link, so the post
# detection has something to reject.
JOURNAL_INDEX = """<html><body>
  <nav><a href="/about">About</a><a href="/contact">Contact</a>
       <a href="https://elsewhere.invalid/journal/x">Partners</a></nav>
  <main>
    <h1>Journal</h1>
    <div class="card"><a href="/journal/why-beam-matters">Why beam matters</a>
      <p>A short teaser.</p></div>
    <div class="card"><a href="/journal/draft-and-the-harbourmaster">Draft and the harbourmaster</a>
      <p>Another teaser.</p></div>
    <div class="card"><a href="/journal/galley-layouts-that-sell">Galley layouts that sell</a>
      <p>One more teaser.</p></div>
  </main>
</body></html>"""

# `/news` links the same three posts, as broker sites routinely do. Used to
# assert the second hop deduplicates rather than re-fetching.
NEWS_INDEX = """<html><body><main><h1>News</h1>
  <a href="/journal/why-beam-matters">Why beam matters</a>
  <a href="/journal/draft-and-the-harbourmaster">Draft and the harbourmaster</a>
  <a href="/journal/galley-layouts-that-sell">Galley layouts that sell</a>
</main></body></html>"""


def _post(headline: str, body: str) -> str:
    return (
        f"<html><body><nav><a href='/contact'>Contact</a></nav><article>"
        f"<h1>{headline}</h1>{body}</article>"
        f"<footer>Copyright 2026.</footer></body></html>"
    )


POST_BODY = """
<p>Beam matters more than length when the marina is completely full during the
height of the Mediterranean season, and a wide platform buys deck space that
guests notice the moment they step aboard for the very first time.</p>
<p>Draft is the constraint nobody mentions until it is far too late in the
season, because the harbourmaster only checks keel depth after the deposit has
already been spent and the itinerary has been confirmed by everyone aboard.</p>
<p>Galley layout wins or loses considerably more sales than raw engine power
ever could, because a guest who cannot see the water while cooking will
remember that particular discomfort for years and years afterwards.</p>
<p>Owners ask about resale value long before they ever ask about warranty
coverage terms, which tells you something genuinely important about how this
ownership market actually thinks about a ten year ownership horizon.</p>
"""

PAGES_2LEVEL = {
    "https://acme.invalid/": HOME_2LEVEL,
    "https://acme.invalid/journal": JOURNAL_INDEX,
    "https://acme.invalid/news": NEWS_INDEX,
    "https://acme.invalid/journal/why-beam-matters": _post("Why beam matters", POST_BODY),
    "https://acme.invalid/journal/draft-and-the-harbourmaster": _post(
        "Draft and the harbourmaster", POST_BODY
    ),
    "https://acme.invalid/journal/galley-layouts-that-sell": _post(
        "Galley layouts that sell", POST_BODY
    ),
}

# A journal index whose posts are one-line stubs: the corpus is real HTML and
# really fetched, but far too thin to describe how anyone writes.
STUB_PAGES = {
    "https://acme.invalid/": HOME_2LEVEL,
    "https://acme.invalid/journal": JOURNAL_INDEX,
    "https://acme.invalid/news": NEWS_INDEX,
    "https://acme.invalid/journal/why-beam-matters": _post(
        "Why beam matters", "<p>Beam matters. More soon.</p>"
    ),
    "https://acme.invalid/journal/draft-and-the-harbourmaster": _post(
        "Draft and the harbourmaster", "<p>Draft matters too. More soon.</p>"
    ),
    "https://acme.invalid/journal/galley-layouts-that-sell": _post(
        "Galley layouts that sell", "<p>Galleys sell boats. More soon.</p>"
    ),
}


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.pages.get(url)

    def robots_allows(self, url):
        return True


class FakeProfileClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def classify(self, articles):
        self.calls += 1
        return self.payload


JUDGEMENT = {
    "register": "warm professional",
    "themes": ["berthing", "seasonality"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["beam", "draft"],
}


def _qualified_broker(domain="acme.invalid"):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nAcme,{domain}\n")
    bid = conn.execute("SELECT id FROM broker").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return conn, bid


def test_fixture_yields_quotes_and_a_discriminating_long_sentence():
    """Guards the fixture itself (see corrections note above), not profile_broker.

    Verified by running this: select_quotes(ARTICLE-extracted-text) returns 2
    quotes for this fixture, and LONG_SENTENCE (214 chars) is one of the
    sentences selected -- so it is a real member of the ranking, not a sentence
    that happens to be irrelevant to it.
    """
    from bce import style
    from bce.articles import extract_article_text

    text = extract_article_text(ARTICLE)
    assert len(text) >= 1500
    assert len(LONG_SENTENCE) > style.MAX_QUOTE_CHARS

    quotes = style.select_quotes([text])
    assert quotes
    assert any(q.startswith(LONG_SENTENCE[:style.MAX_QUOTE_CHARS]) for q in quotes)


def test_writes_a_profile_row():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    ok = profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient(JUDGEMENT))
    # I5: profile_broker now returns a ProfileResult that is truthy exactly when
    # a row was written, so the caller can also see whether classification landed.
    assert bool(ok) is True
    assert ok.written is True
    assert ok.classified is True
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["register"] == "warm professional"
    assert json.loads(row["themes"]) == ["berthing", "seasonality"]
    assert row["avg_sentence_len"] > 0
    assert row["analyzed_at"] is not None


def test_stores_quotes_as_json_and_never_the_article():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient(JUDGEMENT))
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    quotes = json.loads(row["sample_quotes"])
    assert quotes
    for quote in quotes:
        assert len(quote) <= 200
    blob = " ".join(str(v) for v in tuple(row))
    # LONG_SENTENCE is 214 chars and is one of the sentences select_quotes
    # actually picks for this fixture, so it is stored truncated to 200 chars.
    # The full sentence therefore must never appear verbatim in the row -- if
    # the MAX_QUOTE_CHARS truncation were removed, the full sentence would
    # leak in and this assertion would fail.
    assert LONG_SENTENCE not in blob


def test_returns_false_and_writes_nothing_when_no_articles():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": None}
    client = FakeProfileClient(JUDGEMENT)
    assert bool(profile.profile_broker(conn, bid, FakeFetcher(pages), client)) is False
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 0
    assert client.calls == 0


def test_unreachable_homepage_writes_nothing():
    conn, bid = _qualified_broker()
    client = FakeProfileClient(JUDGEMENT)
    assert bool(profile.profile_broker(conn, bid, FakeFetcher({}), client)) is False
    assert client.calls == 0


def test_empty_judgement_still_writes_the_deterministic_half():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    result = profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient({}))
    assert bool(result) is True
    # I5: written, but the judgement half did not land — the caller must be able
    # to say so rather than printing an unqualified "profiled".
    assert result.classified is False
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["avg_sentence_len"] > 0
    assert row["register"] is None


# --- C1: statistics must come from the posts, not the index ------------------

def test_statistics_come_from_the_posts_not_the_journal_index():
    """The defect, end to end: index -> teaser fragments -> a 21-word 'article'."""
    from bce.articles import extract_article_text

    # What the old code would have profiled: the index page's teaser fragments.
    index_text = extract_article_text(JOURNAL_INDEX)
    index_words = style.typical_word_count([index_text])
    index_shape = json.loads(style.structure_pattern([index_text]))
    assert index_words < 30  # ~21 words of card titles and teasers

    conn, bid = _qualified_broker()
    fetcher = FakeFetcher(PAGES_2LEVEL)
    result = profile.profile_broker(conn, bid, fetcher, FakeProfileClient(JUDGEMENT))
    assert bool(result) is True

    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    # The posts are ~146 words each; the index is ~21. The row must describe the
    # posts.
    assert row["typical_word_count"] > 100
    shape = json.loads(row["structure_pattern"])
    assert shape["words_per_paragraph"] > 100
    assert shape["words_per_paragraph"] != index_shape["words_per_paragraph"]
    assert row["avg_sentence_len"] > 20  # long, subordinate-clause sentences

    # The index pages were fetched to find links, and the posts were fetched for
    # their bodies. Both hops really happened.
    assert "https://acme.invalid/journal" in fetcher.calls
    assert "https://acme.invalid/journal/why-beam-matters" in fetcher.calls


def test_second_hop_does_not_refetch_posts_linked_from_two_indexes():
    conn, bid = _qualified_broker()
    fetcher = FakeFetcher(PAGES_2LEVEL)
    profile.profile_broker(conn, bid, fetcher, FakeProfileClient(JUDGEMENT))
    assert len(fetcher.calls) == len(set(fetcher.calls))


def test_second_hop_stays_within_the_article_bound():
    from bce.articles import MAX_ARTICLES_PER_BROKER

    conn, bid = _qualified_broker()
    fetcher = FakeFetcher(PAGES_2LEVEL)
    profile.profile_broker(conn, bid, fetcher, FakeProfileClient(JUDGEMENT))
    post_calls = [c for c in fetcher.calls if c.count("/") > 3]
    assert len(post_calls) <= MAX_ARTICLES_PER_BROKER


def test_thin_corpus_writes_nothing_and_spends_no_api_call():
    """C1's plausibility floor: stub posts must not become a confident row."""
    conn, bid = _qualified_broker()
    client = FakeProfileClient(JUDGEMENT)
    result = profile.profile_broker(conn, bid, FakeFetcher(STUB_PAGES), client)
    assert bool(result) is False
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 0
    assert client.calls == 0


def test_an_editorial_url_that_is_itself_an_article_is_kept():
    """Some brokers publish one long journal page; that needs no second hop."""
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    fetcher = FakeFetcher(pages)
    assert bool(profile.profile_broker(conn, bid, fetcher, FakeProfileClient(JUDGEMENT)))
    assert fetcher.calls == ["https://acme.invalid/", "https://acme.invalid/blog"]


# --- I4: the LLM half is clamped on persist ----------------------------------

def test_overlong_llm_fields_are_clamped_on_persist():
    """A non-conforming response cannot write more than the schema promised."""
    conn, bid = _qualified_broker()
    oversized = {
        "register": "x" * 5000,
        "audience_signal": "y" * 5000,
        "themes": [f"theme {i} " + "t" * 500 for i in range(40)],
        "vocabulary_markers": [f"word {i} " + "w" * 500 for i in range(40)],
    }
    profile.profile_broker(
        conn, bid, FakeFetcher(PAGES_2LEVEL), FakeProfileClient(oversized)
    )
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert len(row["register"]) == profile.MAX_FIELD_CHARS
    assert len(row["audience_signal"]) == profile.MAX_FIELD_CHARS
    for column in ("themes", "vocabulary_markers"):
        items = json.loads(row[column])
        assert len(items) == profile.MAX_LIST_ITEMS
        assert all(len(i) <= profile.MAX_FIELD_CHARS for i in items)


def test_non_string_llm_fields_do_not_reach_the_row():
    conn, bid = _qualified_broker()
    junk = {
        "register": {"nested": "object"},
        "audience_signal": 42,
        "themes": "not a list",
        "vocabulary_markers": [1, 2, {"a": "b"}, "keep me"],
    }
    result = profile.profile_broker(
        conn, bid, FakeFetcher(PAGES_2LEVEL), FakeProfileClient(junk)
    )
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["register"] is None
    assert row["audience_signal"] is None
    assert json.loads(row["themes"]) == []
    assert json.loads(row["vocabulary_markers"]) == ["keep me"]
    assert result.classified is False


def test_reprofiling_replaces_rather_than_duplicates():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    f, c = FakeFetcher(pages), FakeProfileClient(JUDGEMENT)
    profile.profile_broker(conn, bid, f, c)
    profile.profile_broker(conn, bid, f, c)
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 1
