import io

from fastapi.testclient import TestClient

from bce import cli, db, discover
from bce.web.app import create_app


def _client(tmp_path):
    """A client that carries the CSRF token on every request.

    The token is required on state-changing endpoints since 2026-09-02
    (IT risk assessment, finding 3). Attaching it here rather than at each
    call site keeps these tests about what they were about; the control
    itself is covered in `test_web_security.py`, including that a POST
    without it is refused.
    """
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    app = create_app(path)
    client = TestClient(app, headers={"X-CSRF-Token": app.state.csrf_token})
    return client, path


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


def test_manual_add_rejects_a_blank_name(tmp_path):
    """A raw POST can bypass the form's `required` attribute. Without the
    guard, parse_rows silently skips the row, import_csv reports 0 inserted,
    and the handler used to read that as 'already in the list' — a false
    success for a broker that was never validly submitted."""
    client, path = _client(tmp_path)
    r = client.post("/add/manual", data={"name": "", "domain": "acme.invalid"},
                    follow_redirects=True)
    assert "name is required" in r.text.lower()
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0


def test_manual_add_rejects_a_whitespace_only_name(tmp_path):
    client, path = _client(tmp_path)
    r = client.post("/add/manual", data={"name": "   ", "domain": "acme.invalid"},
                    follow_redirects=True)
    assert "name is required" in r.text.lower()
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0


def test_manual_add_preserves_commas_and_quotes_in_name_and_region(tmp_path):
    """Manual add builds a synthetic CSV row and routes it through import_csv
    rather than a second insert path. A name or region containing a comma or a
    double quote is exactly what would corrupt a hand-built CSV string; the
    csv.writer/DictReader round trip must return them unchanged."""
    client, path = _client(tmp_path)
    client.post(
        "/add/manual",
        data={
            "name": 'Acme, Inc. "The Best"',
            "domain": "acme.invalid",
            "region": "Med, Adriatic",
        },
        follow_redirects=True,
    )
    conn = db.connect(path)
    rows = discover.list_brokers(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == 'Acme, Inc. "The Best"'
    assert rows[0]["region"] == "Med, Adriatic"
