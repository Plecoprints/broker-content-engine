"""Operator-panel hardening (IT risk assessment 2026-09-02, findings 2-5, 8).

Every finding here had the same shape: a control that was assumed in a
comment rather than applied in code. So each test asserts the control is
*enforced*, and several assert it cannot be switched off by accident, which
is the failure mode that produced the findings in the first place.
"""
import io
import os

import pytest
from fastapi.testclient import TestClient

from bce import cli, db
from bce.web.app import MAX_UPLOAD_BYTES, PASSWORD_ENV, RATE_LIMIT_REQUESTS, create_app


def _app(tmp_path, name="sec.db"):
    path = str(tmp_path / name)
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return create_app(path)


def _csv(text="name,domain\nAcme,acme.invalid\n"):
    return {"file": ("brokers.csv", io.BytesIO(text.encode()), "text/csv")}


# --- CSRF (finding 3) ----------------------------------------------------

def test_a_post_without_a_token_is_refused(tmp_path):
    client = TestClient(_app(tmp_path))
    assert client.post("/add/manual", data={"name": "A", "domain": "a.invalid"}).status_code == 403
    assert client.post("/add/csv", files=_csv()).status_code == 403


def test_a_post_with_the_wrong_token_is_refused(tmp_path):
    client = TestClient(_app(tmp_path))
    r = client.post("/add/manual?csrf=not-the-token", data={"name": "A", "domain": "a.invalid"})
    assert r.status_code == 403


def test_the_query_parameter_the_real_forms_use_is_accepted(tmp_path):
    """The templates put the token in the form `action`, so this is the path
    a browser actually exercises."""
    app = _app(tmp_path)
    client = TestClient(app)
    r = client.post(
        f"/add/manual?csrf={app.state.csrf_token}",
        data={"name": "Acme", "domain": "acme.invalid"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303, 307)


def test_the_header_is_also_accepted(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app, headers={"X-CSRF-Token": app.state.csrf_token})
    r = client.post("/add/csv", files=_csv(), follow_redirects=False)
    assert r.status_code in (302, 303, 307)


def test_reads_do_not_require_a_token(tmp_path):
    """A CSRF control that blocked GETs would be a broken app, not a safe one."""
    assert TestClient(_app(tmp_path)).get("/").status_code == 200


def test_every_form_in_the_ui_carries_a_token(tmp_path):
    """Guards the half that breaks silently: if a template loses its token the
    control still 'works' and the page simply stops functioning."""
    body = TestClient(_app(tmp_path)).get("/add").text
    assert body.count("csrf=") >= 2


def test_the_token_is_unguessable(tmp_path):
    a, b = _app(tmp_path, "a.db"), _app(tmp_path, "b.db")
    assert a.state.csrf_token != b.state.csrf_token
    assert len(a.state.csrf_token) >= 32


# --- authentication (finding 2) ------------------------------------------

def test_no_password_means_no_auth_on_loopback(tmp_path, monkeypatch):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert TestClient(_app(tmp_path)).get("/").status_code == 200


def test_a_password_is_enforced_on_every_route(tmp_path, monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "hunter2")
    client = TestClient(_app(tmp_path))
    assert client.get("/").status_code == 401
    assert client.get("/add").status_code == 401
    assert client.post("/add/manual", data={}).status_code == 401


def test_the_right_password_is_accepted_and_a_wrong_one_is_not(tmp_path, monkeypatch):
    monkeypatch.setenv(PASSWORD_ENV, "hunter2")
    client = TestClient(_app(tmp_path))
    assert client.get("/", auth=("operator", "hunter2")).status_code == 200
    assert client.get("/", auth=("operator", "hunter3")).status_code == 401


def test_auth_is_checked_before_csrf(tmp_path, monkeypatch):
    """An unauthenticated caller must not be able to probe CSRF behaviour."""
    monkeypatch.setenv(PASSWORD_ENV, "hunter2")
    client = TestClient(_app(tmp_path))
    assert client.post("/add/manual?csrf=guess", data={}).status_code == 401


# --- binding (finding 2, the enforcement half) ---------------------------

@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "10.0.0.4"])
def test_serving_beyond_loopback_without_a_password_is_refused(host, monkeypatch, capsys):
    monkeypatch.delenv(PASSWORD_ENV, raising=False)
    assert cli.cmd_serve("/tmp/never-created.db", host=host) == 1
    assert "refused" in capsys.readouterr().out


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_are_recognised(host):
    assert cli.is_loopback_host(host) is True


# --- upload ceiling (finding 4) ------------------------------------------

def test_an_oversized_upload_is_refused_without_being_buffered(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app, headers={"X-CSRF-Token": app.state.csrf_token})
    oversized = "name,domain\n" + ("A,a.invalid\n" * (MAX_UPLOAD_BYTES // 5))
    r = client.post("/add/csv", files=_csv(oversized), follow_redirects=True)
    assert "larger than" in r.text


def test_a_normal_broker_list_is_well_under_the_ceiling(tmp_path):
    """The ceiling must not be near legitimate use, or it becomes the bug."""
    realistic = "name,domain\n" + "".join(
        f"Brokerage Number {i},brokerage-{i}.invalid\n" for i in range(50)
    )
    assert len(realistic.encode()) < MAX_UPLOAD_BYTES // 10


# --- throttling (finding 7) ----------------------------------------------

def test_state_changing_requests_are_throttled(tmp_path):
    app = _app(tmp_path)
    client = TestClient(app, headers={"X-CSRF-Token": app.state.csrf_token})
    codes = [
        client.post("/add/manual", data={"name": "A", "domain": "a.invalid"},
                    follow_redirects=False).status_code
        for _ in range(RATE_LIMIT_REQUESTS + 5)
    ]
    assert 429 in codes, "no request was ever throttled"


def test_reads_are_never_throttled(tmp_path):
    """Throttling the read path would make the panel unusable while browsing."""
    client = TestClient(_app(tmp_path))
    codes = [client.get("/").status_code for _ in range(RATE_LIMIT_REQUESTS + 5)]
    assert set(codes) == {200}
