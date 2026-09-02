"""Gate 3 (Original) needs something to compare a draft against, and spec
§10.3 forbids storing full article text in `voice_profile`. The resolution
(spec §10.3 amendment, `bce.fingerprint`'s module docstring): profiling
fingerprints the same article text it already fetches and discards --
`bce.profile.profile_broker` persists shingle *hashes* of it to
`source_fingerprint`, never the text itself.
"""
import json

from bce import db, discover, fingerprint, profile
from bce.articles import extract_article_text

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

HOME = '<html><body><a href="/blog">Blog</a> Our 80 ft fleet</body></html>'

JUDGEMENT = {
    "register": "warm professional",
    "themes": ["berthing", "seasonality"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["beam", "draft"],
}


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

    def classify(self, articles):
        return self.payload


def _qualified_broker(domain="acme.invalid"):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nAcme,{domain}\n")
    bid = conn.execute("SELECT id FROM broker").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return conn, bid


def _pages():
    return {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}


def test_profiling_persists_source_fingerprints_for_the_broker():
    conn, bid = _qualified_broker()
    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient(JUDGEMENT))

    rows = conn.execute(
        "SELECT shingle_hash FROM source_fingerprint WHERE broker_id=?", (bid,)
    ).fetchall()
    assert len(rows) > 0
    assert all(isinstance(r["shingle_hash"], int) for r in rows)


def test_persisted_fingerprints_match_shingle_hashes_of_the_extracted_article():
    conn, bid = _qualified_broker()
    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient(JUDGEMENT))

    stored = {
        r["shingle_hash"]
        for r in conn.execute(
            "SELECT shingle_hash FROM source_fingerprint WHERE broker_id=?", (bid,)
        ).fetchall()
    }
    expected = fingerprint.shingle_hashes(extract_article_text(ARTICLE))
    assert stored == expected


def test_no_articles_persists_no_fingerprints():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": None}
    profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient(JUDGEMENT))

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM source_fingerprint WHERE broker_id=?", (bid,)
    ).fetchone()["c"]
    assert count == 0


def test_reprofiling_does_not_duplicate_fingerprint_rows():
    conn, bid = _qualified_broker()
    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient(JUDGEMENT))
    first_count = conn.execute(
        "SELECT COUNT(*) AS c FROM source_fingerprint WHERE broker_id=?", (bid,)
    ).fetchone()["c"]

    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient(JUDGEMENT))
    second_count = conn.execute(
        "SELECT COUNT(*) AS c FROM source_fingerprint WHERE broker_id=?", (bid,)
    ).fetchone()["c"]

    assert second_count == first_count


def test_fingerprints_persist_even_when_classification_fails():
    """Fingerprinting is deterministic hashing of already-fetched text, not
    an LLM call -- an empty/failed judgement must not stop it (mirrors the
    existing "statistics still land" behaviour for avg_sentence_len etc.).
    """
    conn, bid = _qualified_broker()
    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient({}))

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM source_fingerprint WHERE broker_id=?", (bid,)
    ).fetchone()["c"]
    assert count > 0


def test_source_fingerprint_table_never_receives_a_text_value():
    """Literal enforcement of spec §10.3: even if some future caller tried
    to smuggle text into this table, the column is INTEGER-typed and
    genuinely cannot hold it.
    """
    conn, bid = _qualified_broker()
    profile.profile_broker(conn, bid, FakeFetcher(_pages()), FakeProfileClient(JUDGEMENT))
    cols = {r["name"]: r["type"] for r in conn.execute("PRAGMA table_info(source_fingerprint)")}
    assert cols["shingle_hash"] == "INTEGER"
