"""The keyword panel (spec §5b, §9 "Keyword panel") on the draft viewer.

Built as one reusable Jinja2 macro (`_keyword_panel.html`), not inlined, so
spec §9b can reuse it verbatim in the broker portal later. Fixtures are
built directly against the schema (broker/angle/draft/keyword/draft_keyword)
rather than through `bce.seed` -- seeding keywords onto the example drafts is
a separate follow-up task, and `seed.py` is off-limits regardless.
"""
import re

from fastapi.testclient import TestClient

from bce import db, keywords
from bce.web.app import create_app

_NONE_RE = re.compile(r"\bNone\b")


def _conn(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    return path, conn


def _broker_with_long_draft(conn, *, with_keywords: bool) -> tuple[int, int]:
    """A minimal broker -> angle -> long draft chain. Returns (broker_id, draft_id)."""
    bid = conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Keyword Test Yachts', "
        "'keywordtest.invalid', 'manual')"
    ).lastrowid
    aid = conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (?, 'Test Angle')", (bid,)
    ).lastrowid
    did = conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
        "VALUES (?, 'Body text here.', 3, 'pending_review', 'long')",
        (aid,),
    ).lastrowid
    if with_keywords:
        kw1 = conn.execute(
            "INSERT INTO keyword (phrase, volume, difficulty, database, "
            "measured_at, qualifies, source, competitor_brand, segment_relevant, "
            "editorial) VALUES ('catamaran for sale', 8100, 25, 'us', "
            "'2026-09-01', 1, 'semrush', 0, 1, 1)"
        ).lastrowid
        kw2 = conn.execute(
            "INSERT INTO keyword (phrase, volume, difficulty, database, "
            "measured_at, qualifies, source, competitor_brand, segment_relevant, "
            "editorial) VALUES ('catamarans for sale', 4400, 24, 'us', "
            "'2026-09-01', 1, 'semrush', 0, 1, 1)"
        ).lastrowid
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?,?,'primary')",
            (did, kw1),
        )
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?,?,'secondary')",
            (did, kw2),
        )
    conn.commit()
    return bid, did


def test_keyword_panel_shows_primary_and_secondary_with_metrics(tmp_path):
    path, conn = _conn(tmp_path)
    bid, _ = _broker_with_long_draft(conn, with_keywords=True)
    conn.close()

    client = TestClient(create_app(path))
    body = client.get(f"/broker/{bid}/drafts").text

    assert "catamaran for sale" in body
    assert "catamarans for sale" in body
    # Difficulty and volume for at least the primary keyword.
    assert "8100" in body
    assert "25" in body
    # Measurement date shown beside the figure (spec §5b).
    assert "2026-09-01" in body


def test_keyword_panel_shows_the_active_thresholds(tmp_path):
    path, conn = _conn(tmp_path)
    bid, _ = _broker_with_long_draft(conn, with_keywords=True)
    conn.close()

    client = TestClient(create_app(path))
    body = client.get(f"/broker/{bid}/drafts").text

    assert str(keywords.MAX_DIFFICULTY) in body
    assert str(keywords.MIN_VOLUME) in body


def test_keyword_panel_degrades_honestly_when_no_keywords_baked_in(tmp_path):
    """Matches the existing 'condensation failed' panels' honesty -- says so
    plainly, does not render an empty box.
    """
    path, conn = _conn(tmp_path)
    bid, _ = _broker_with_long_draft(conn, with_keywords=False)
    conn.close()

    client = TestClient(create_app(path))
    body = client.get(f"/broker/{bid}/drafts").text

    assert "no qualifying keyword" in body.lower()


def test_keyword_panel_never_leaks_a_literal_none(tmp_path):
    """Follows the existing guard test's pattern (test_web_drafts.py's
    test_no_literal_none_leaks_for_any_seeded_broker) -- a keyword with a
    NULL difficulty/volume/measured_at must render 'unknown', never 'None'.
    """
    path, conn = _conn(tmp_path)
    bid, did = _broker_with_long_draft(conn, with_keywords=False)
    kw = conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, "
        "measured_at, qualifies, source, competitor_brand, segment_relevant, "
        "editorial) VALUES ('catamaran refit', NULL, NULL, 'us', NULL, 0, "
        "'semrush', 0, 1, 1)"
    ).lastrowid
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?,?,'primary')",
        (did, kw),
    )
    conn.commit()
    conn.close()

    client = TestClient(create_app(path))
    r = client.get(f"/broker/{bid}/drafts")
    assert r.status_code == 200
    assert not _NONE_RE.search(r.text)
    assert "unknown" in r.text.lower()


def test_keyword_panel_is_a_reusable_macro_not_inlined():
    """spec §9b reuses this component verbatim in the broker portal later --
    it must exist as its own template partial, not be copy-pasted into
    draft_viewer.html.
    """
    from pathlib import Path

    templates_dir = Path("src/bce/web/templates")
    partial = templates_dir / "_keyword_panel.html"
    assert partial.exists()
    assert "macro keyword_panel" in partial.read_text()

    viewer = (templates_dir / "draft_viewer.html").read_text()
    assert "from \"_keyword_panel.html\" import keyword_panel" in viewer
    # The viewer calls the macro; it does not redefine the table markup itself.
    assert "keyword_panel(long_keywords" in viewer


def test_existing_no_literal_none_guard_still_passes_with_seeded_data(tmp_path):
    """The pre-existing whole-suite guard (test_web_drafts.py) must still
    pass now that every seeded broker's page also renders the (keyword-less)
    panel -- confirms the "no keywords" branch never leaks a bare None for
    real seeded data, not just this file's own minimal fixture.
    """
    from bce import discover, seed

    path = str(tmp_path / "ui2.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    conn.close()

    client = TestClient(create_app(path))
    conn = db.connect(path)
    for row in discover.list_brokers(conn):
        r = client.get(f"/broker/{row['id']}/drafts")
        assert r.status_code == 200
        assert not _NONE_RE.search(r.text), f"literal None leaked for {row['name']}"
