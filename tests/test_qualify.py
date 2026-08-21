from bce import db, discover, qualify


class FakeFetcher:
    def __init__(self, pages: dict[str, str | None]):
        self.pages = pages

    def get(self, url: str) -> str | None:
        return self.pages.get(url)

    def robots_allows(self, url: str) -> bool:
        return self.pages.get(url) is not None


def _conn_with_broker(domain="acme.com"):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nAcme,{domain}\n")
    bid = conn.execute("SELECT id FROM broker").fetchone()["id"]
    return conn, bid


def test_unreachable_homepage_fails_qualification():
    conn, bid = _conn_with_broker()
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher({}))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "unreachable_or_disallowed"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_editorial"] is None
    assert row["has_newsletter"] is None


def test_below_threshold_fails():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 40 ft boats'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "below_length_threshold"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_editorial"] == 1
    assert row["has_newsletter"] == 0


def test_no_publishing_channel_fails():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": "We sell 80 ft catamarans"}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "no_publishing_channel"


def test_passing_broker_is_marked_qualified():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    assert verdict["reason"] == "passed"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["qualified"] == 1
    assert row["robots_allowed"] == 1


def test_affinity_recorded_but_does_not_affect_verdict():
    conn, bid = _conn_with_broker()
    # Sunreef mention present, but boat too small -> still fails on length
    pages = {"https://acme.com/": '<a href="/news">News</a> Sunreef for sale, 30 ft'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "below_length_threshold"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["sunreef_affinity"] == "lists_inventory"
    assert "Sunreef" in row["affinity_evidence"]


def test_segment_evidence_records_detected_length():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> 90 ft yachts'}
    qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    row = conn.execute("SELECT segment_evidence FROM broker WHERE id=?", (bid,)).fetchone()
    assert "90" in row["segment_evidence"]


def test_newsletter_only_broker_passes():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": "Our 80 ft fleet. Sign up for our newsletter."}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    assert verdict["reason"] == "passed"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_newsletter"] == 1
    assert row["has_editorial"] == 0


def test_editorial_only_broker_passes():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_editorial"] == 1
    assert row["has_newsletter"] == 0
