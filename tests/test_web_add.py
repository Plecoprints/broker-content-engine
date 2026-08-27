import io

from fastapi.testclient import TestClient

from bce import cli, db, discover
from bce.web.app import create_app


def _client(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return TestClient(create_app(path)), path


def _csv(text):
    return {"file": ("brokers.csv", io.BytesIO(text.encode()), "text/csv")}


def test_add_page_renders(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/add")
    assert r.status_code == 200
    assert "csv" in r.text.lower()


def test_csv_upload_imports_brokers(tmp_path):
    client, path = _client(tmp_path)
    r = client.post("/add/csv", files=_csv("name,domain\nAcme,acme.invalid\n"),
                    follow_redirects=True)
    assert r.status_code == 200
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1


def test_csv_upload_tolerates_title_case_headers(tmp_path):
    """The exact silent no-op fixed at the CLI — it must not return in the UI."""
    client, path = _client(tmp_path)
    client.post("/add/csv", files=_csv("Name,Domain\nAcme,acme.invalid\n"),
                follow_redirects=True)
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1


def test_bad_headers_report_what_was_found(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/add/csv", files=_csv("company,website\nAcme,acme.invalid\n"),
                    follow_redirects=True)
    assert "company" in r.text and "website" in r.text


def test_cap_refuses_the_whole_upload(tmp_path):
    client, path = _client(tmp_path)
    rows = "name,domain\n" + "".join(f"B{i},b{i}.invalid\n" for i in range(cli.MAX_BROKERS + 5))
    r = client.post("/add/csv", files=_csv(rows), follow_redirects=True)
    assert "cap" in r.text.lower()
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0, "refusal must insert nothing"


def test_manual_add_creates_a_broker(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/manual", data={"name": "Acme", "domain": "acme.invalid",
                                     "region": "Med"}, follow_redirects=True)
    conn = db.connect(path)
    rows = discover.list_brokers(conn)
    assert len(rows) == 1 and rows[0]["region"] == "Med"


def test_manual_add_normalizes_a_url_in_the_domain_field(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/manual", data={"name": "Acme", "domain": "https://www.acme.invalid/"},
                follow_redirects=True)
    conn = db.connect(path)
    assert discover.list_brokers(conn)[0]["domain"] == "acme.invalid"


def test_manual_add_rejects_a_non_hostname(tmp_path):
    client, path = _client(tmp_path)
    r = client.post("/add/manual", data={"name": "Acme", "domain": "not a domain"},
                    follow_redirects=True)
    assert "not a domain" in r.text
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0


def test_duplicate_domain_is_reported_not_silently_dropped(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/csv", files=_csv("name,domain\nAcme,acme.invalid\n"), follow_redirects=True)
    r = client.post("/add/csv", files=_csv("name,domain\nAcme Again,acme.invalid\n"),
                    follow_redirects=True)
    assert "0" in r.text
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1
