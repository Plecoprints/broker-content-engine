"""Draft viewer (spec §9 UI, task: draft-viewer). Read-only, localhost, no auth."""
import re

from fastapi.testclient import TestClient

from bce import db, discover, seed
from bce.web.app import create_app

_NONE_RE = re.compile(r"\bNone\b")


def _client(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    conn.close()
    return TestClient(create_app(path))


def _broker_id(tmp_path, domain):
    conn = db.connect(str(tmp_path / "ui.db"))
    row = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()
    conn.close()
    return row["id"]


def test_drafts_page_renders_for_broker_with_all_three_drafts(tmp_path):
    """Spec v0.6 §5: three formats, not two -- meridian-yacht.invalid is the
    fully-profiled broker seeded with long, medium, and short (test_seed.py).
    """
    client = _client(tmp_path)
    broker_id = _broker_id(tmp_path, "meridian-yacht.invalid")
    r = client.get(f"/broker/{broker_id}/drafts")
    assert r.status_code == 200
    body = r.text
    assert "Meridian Yacht Brokers" in body
    assert "meridian-yacht.invalid" in body
    # The angle.
    assert "Bluewater Ready" in body
    # The long draft body and its word count.
    assert "bluewater passage" in body
    assert "477" in body
    # The medium draft body and its word count.
    assert "delivery skipper earns their fee twice over" in body
    assert "603" in body
    # The short draft body and its word count.
    assert "checklist, not a brochure" in body
    assert "145" in body


def test_drafts_page_shows_degraded_broker_short_failed_state(tmp_path):
    client = _client(tmp_path)
    broker_id = _broker_id(tmp_path, "anchorbay.invalid")
    r = client.get(f"/broker/{broker_id}/drafts")
    assert r.status_code == 200
    body = r.text
    assert "Anchor Bay Yachts" in body
    # The long draft is present.
    assert "haul-out" in body
    # anchorbay has neither a medium nor a short draft seeded; both must
    # degrade honestly, not render as blank panels.
    assert "medium" in body.lower() and "failed" in body.lower()
    assert "short condensation failed" in body.lower()


def test_broker_with_no_drafts_gets_empty_state_not_404(tmp_path):
    client = _client(tmp_path)
    # Coral Harbor Yachts is profiled but was never drafted in the seed data.
    broker_id = _broker_id(tmp_path, "coralharbor.invalid")
    r = client.get(f"/broker/{broker_id}/drafts")
    assert r.status_code == 200
    assert "no draft" in r.text.lower()


def test_unknown_broker_id_is_404(tmp_path):
    client = _client(tmp_path)
    r = client.get("/broker/999999/drafts")
    assert r.status_code == 404


def test_unvetted_banner_present(tmp_path):
    client = _client(tmp_path)
    broker_id = _broker_id(tmp_path, "meridian-yacht.invalid")
    body = client.get(f"/broker/{broker_id}/drafts").text
    assert "unvetted" in body.lower()
    assert "pending_review" in body or "pending review" in body.lower()


def test_no_literal_none_leaks_for_any_seeded_broker(tmp_path):
    client = _client(tmp_path)
    conn = db.connect(str(tmp_path / "ui.db"))
    for row in discover.list_brokers(conn):
        r = client.get(f"/broker/{row['id']}/drafts")
        assert r.status_code == 200, row["name"]
        assert not _NONE_RE.search(r.text), f"literal None leaked for {row['name']}"


def test_shortlist_links_to_drafts_page_for_brokers_with_drafts(tmp_path):
    client = _client(tmp_path)
    meridian_id = _broker_id(tmp_path, "meridian-yacht.invalid")
    coral_id = _broker_id(tmp_path, "coralharbor.invalid")
    body = client.get("/").text
    assert f"/broker/{meridian_id}/drafts" in body
    assert f"/broker/{coral_id}/drafts" not in body
