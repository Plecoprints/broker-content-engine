"""Operator-approved shortlists (spec §5 Stage 2, revised 2026-09-02).

The operator vets brokers by hand and submits a shortlist they have already
approved. Stage 2 stops being a gate on broker quality — a detector reading a
homepage does not overrule someone who knows the firm — and becomes a
readability check that cannot reject anyone.

The distinction these tests protect: `qualified` now records *who decided*,
and a crawl must never overwrite a person's answer. But the crawl still runs,
because it reports the one thing the operator cannot see by eye — whether the
fetcher can read the site at all, which decides whether Stage 3 can profile
them.
"""
from bce import db, discover, qualify

CSV = "name,domain\nAcme Yachts,acme.invalid\nBeta Marine,beta.invalid\n"


def _conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


class _Shell:
    """A client-rendered site: 200 OK and an empty app shell, so every
    detector reads a blank page and would ordinarily reject."""

    def robots_allows(self, url):
        return True

    def get(self, url):
        return '<html><body><div id="root"></div></body></html>'


def _bid(conn, domain="acme.invalid"):
    return conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]


# --- import marks them approved ------------------------------------------

def test_approved_import_marks_brokers_qualified_immediately():
    conn = _conn()
    assert discover.import_csv(conn, CSV, approved=True) == 2
    rows = conn.execute("SELECT qualified, qualified_reason FROM broker").fetchall()
    assert all(r["qualified"] == 1 for r in rows)
    assert all(r["qualified_reason"] == discover.OPERATOR_APPROVED for r in rows)


def test_approved_brokers_are_immediately_ready_to_profile():
    """The point of the change. Profiling and drafting both select
    `WHERE qualified = 1`, so without this the shortlist would sit inert."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    assert len(discover.list_brokers(conn, qualified=True)) == 2


def test_a_plain_import_is_unchanged():
    """The crawl-first path still exists for anyone who wants it; `approved`
    is opt-in, not the new default."""
    conn = _conn()
    discover.import_csv(conn, CSV)
    rows = conn.execute("SELECT qualified, qualified_reason FROM broker").fetchall()
    assert all(r["qualified"] is None for r in rows)
    assert all(r["qualified_reason"] is None for r in rows)


# --- the crawl cannot overrule the operator ------------------------------

def test_a_crawl_never_downgrades_an_operator_approved_broker():
    """The load-bearing guarantee. This site is unreadable, so every detector
    fails and the verdict would be `below_length_threshold` — which for a
    crawl-qualified broker means rejected. The operator said yes, so it does
    not."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    bid = _bid(conn)

    verdict = qualify.qualify_broker(conn, bid, _Shell())

    row = conn.execute(
        "SELECT qualified, qualified_reason FROM broker WHERE id=?", (bid,)
    ).fetchone()
    assert row["qualified"] == 1
    assert row["qualified_reason"] == discover.OPERATOR_APPROVED
    assert verdict["qualified"] is True
    assert "advisory" in verdict["reason"]


def test_the_crawl_still_reports_that_the_site_is_unreadable():
    """Not a formality. The operator opens the site in a browser and sees it
    rendered; the fetcher sees an empty shell. That decides whether Stage 3
    can profile them, and it is invisible to manual review."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    verdict = qualify.qualify_broker(conn, _bid(conn), _Shell())
    assert verdict["render_suspect"] is True
    assert verdict["visible_text_chars"] < qualify.RENDER_SUSPICION_CHARS


def test_the_crawl_still_records_its_evidence():
    """Advisory does not mean discarded — the detector findings are still
    written, so the operator can see what the crawler made of each site."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    bid = _bid(conn)
    qualify.qualify_broker(conn, bid, _Shell())
    row = conn.execute(
        "SELECT robots_allowed, has_editorial FROM broker WHERE id=?", (bid,)
    ).fetchone()
    assert row["robots_allowed"] == 1


def test_a_crawl_first_broker_can_still_be_rejected():
    """The advisory rule is scoped to operator-approved brokers only. Without
    it, this change would silently disable qualification for everyone."""
    conn = _conn()
    discover.import_csv(conn, CSV)  # not approved
    bid = _bid(conn)
    qualify.qualify_broker(conn, bid, _Shell())
    row = conn.execute("SELECT qualified FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["qualified"] == 0


def test_approved_brokers_are_still_picked_up_by_the_audit():
    """Regression. `--approved` sets qualified=1, and `unqualified_brokers`
    selected `WHERE qualified IS NULL` — so the audit found nothing to audit
    and reported every site readable. It failed silently and looked correct,
    which is why this is asserted rather than remembered."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    assert len(discover.unqualified_brokers(conn, 10)) == 2


def test_an_audited_broker_is_not_re_crawled():
    """The other direction: once audited, they drop out, so re-running does
    not re-crawl sites that have already been visited."""
    conn = _conn()
    discover.import_csv(conn, CSV, approved=True)
    for row in discover.unqualified_brokers(conn, 10):
        qualify.qualify_broker(conn, row["id"], _Shell())
    assert discover.unqualified_brokers(conn, 10) == []
