import json

from bce import db, discover, profile

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


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
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
    assert ok is True
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
    assert profile.profile_broker(conn, bid, FakeFetcher(pages), client) is False
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 0
    assert client.calls == 0


def test_unreachable_homepage_writes_nothing():
    conn, bid = _qualified_broker()
    client = FakeProfileClient(JUDGEMENT)
    assert profile.profile_broker(conn, bid, FakeFetcher({}), client) is False
    assert client.calls == 0


def test_empty_judgement_still_writes_the_deterministic_half():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    assert profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient({})) is True
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["avg_sentence_len"] > 0
    assert row["register"] is None


def test_reprofiling_replaces_rather_than_duplicates():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    f, c = FakeFetcher(pages), FakeProfileClient(JUDGEMENT)
    profile.profile_broker(conn, bid, f, c)
    profile.profile_broker(conn, bid, f, c)
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 1
