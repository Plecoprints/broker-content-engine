from fastapi.testclient import TestClient

from bce import db, seed
from bce.web.app import create_app


def _client(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    conn.close()
    return TestClient(create_app(path))


def test_shortlist_page_renders(tmp_path):
    r = _client(tmp_path).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_shortlist_shows_every_broker(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    conn = db.connect(str(tmp_path / "ui.db"))
    from bce import discover
    for row in discover.list_brokers(conn):
        assert row["name"] in body, f"{row['name']} missing from the page"


def test_shortlist_shows_rejection_reasons(tmp_path):
    body = _client(tmp_path).get("/").text
    assert "below_length_threshold" in body


def test_shortlist_renders_a_broker_with_no_profile_without_erroring(tmp_path):
    """Half the seed rows have NULLs somewhere. None may raise."""
    assert _client(tmp_path).get("/").status_code == 200


def test_empty_database_renders_an_empty_state(tmp_path):
    path = str(tmp_path / "empty.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    r = TestClient(create_app(path)).get("/")
    assert r.status_code == 200
    assert "no brokers" in r.text.lower()
