from datetime import date, timedelta

from bce import db, discover, qualify


class FakeFetcher:
    def __init__(self, pages: dict[str, str | None]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str) -> str | None:
        self.requested.append(url)
        return self.pages.get(url)

    def robots_allows(self, url: str) -> bool:
        return self.pages.get(url) is not None


def _dated_post(days_ago: int) -> str:
    """An editorial page carrying a real publication date (spec §4, 12 months)."""
    when = (date.today() - timedelta(days=days_ago)).isoformat()
    return (
        "<html><body><article><h1>A post</h1>"
        f'<time datetime="{when}">{when}</time>'
        "<p>Prose about catamarans.</p></article></body></html>"
    )


def _undated_post() -> str:
    return "<html><body><article><p>No date anywhere in here.</p></article></body></html>"


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
    pages = {
        "https://acme.com/": '<a href="/blog">Blog</a> Our 40 ft boats',
        "https://acme.com/blog": _dated_post(10),
    }
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
    pages = {
        "https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet',
        "https://acme.com/blog": _dated_post(30),
    }
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
    pages = {
        "https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet',
        "https://acme.com/blog": _dated_post(200),
    }
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_editorial"] == 1
    assert row["has_newsletter"] == 0


# --- C1: detectors must see extracted text, not raw markup -------------------

REALISTIC_HOMEPAGE = """<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'>
  <title>Coastline Yacht Brokerage</title>
  <style>.m-b-30{margin-bottom:30px}.w-80{width:80%}</style>
  <script>
    var store = {}; store.subscribe(function(state){ return state; });
    var carousel = { width: '150', height: '80', speed: '300' };
  </script>
</head>
<body class='m-b-30'>
  <nav class='nav m-b-30'>
    <img src='/logo.png' width='150' height='60' alt='Coastline'>
    <a href='/fleet'>Our Fleet</a>
    <a href='/blog'>Journal</a>
    <a href='/contact'>Contact</a>
  </nav>
  <section class='hero w-80'>
    <h1>Coastline Yacht Brokerage</h1>
    <p>Family cruising catamarans from 42' to 55', based in Palma.</p>
    <p>Our largest current listing is a 14 m sailing catamaran.</p>
  </section>
  <footer class='m-b-30'>
    <p>Follow us: <a href='https://youtube.com/c/coastline'>Subscribe to our
       YouTube channel</a></p>
    <p>&copy; 2026 Coastline. You may subscribe or withdraw consent at any
       time.</p>
  </footer>
</body>
</html>
"""


def test_realistic_homepage_under_60ft_is_rejected():
    """The C1 regression: on real markup, attribute and script numbers used to
    become vessel lengths (width='150' -> 150ft), so a broker selling 42-55ft
    boats qualified with reason 'passed'."""
    conn, bid = _conn_with_broker()
    pages = {
        "https://acme.com/": REALISTIC_HOMEPAGE,
        "https://acme.com/blog": _dated_post(20),
    }
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "below_length_threshold"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    # 55' is the largest real length on the page; 14 m == 46 ft.
    assert row["segment_evidence"] == "max_detected_length_ft=55"


def test_realistic_homepage_javascript_subscribe_is_not_a_newsletter():
    """C1b: the only 'subscribe' on this page is JS and a YouTube link."""
    conn, bid = _conn_with_broker()
    pages = {
        "https://acme.com/": REALISTIC_HOMEPAGE,
        "https://acme.com/blog": _dated_post(20),
    }
    qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_newsletter"] == 0
    # no minified JS persisted as the operator's justification
    assert not row["newsletter_evidence"]


def test_evidence_columns_store_prose_not_markup():
    conn, bid = _conn_with_broker()
    homepage = REALISTIC_HOMEPAGE.replace(
        "<h1>Coastline Yacht Brokerage</h1>",
        "<h1>Coastline Yacht Brokerage</h1><p>Sunreef 80 for sale, 80 ft.</p>",
    )
    pages = {
        "https://acme.com/": homepage,
        "https://acme.com/blog": _dated_post(20),
    }
    qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["sunreef_affinity"] == "lists_inventory"
    assert "Sunreef" in row["affinity_evidence"]
    assert "<" not in row["affinity_evidence"]
    assert "class=" not in row["affinity_evidence"]
