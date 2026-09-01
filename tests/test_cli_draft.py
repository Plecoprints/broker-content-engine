import json

from bce import cli, db, discover, drafting


def _db(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    return str(p)


def _broker(conn, domain, name=None):
    name = name or domain.split(".")[0].title()
    discover.import_csv(conn, f"name,domain\n{name},{domain}\n")
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return bid


def _profile(conn, bid, register="warm professional"):
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, structure_pattern, "
        "vocabulary_markers, themes, sample_quotes) VALUES (?,?,?,?,?,?)",
        (bid, register, json.dumps({}), json.dumps([]), json.dumps([]), json.dumps([])),
    )
    conn.commit()


def _drafted(conn, bid):
    aid = conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (?, 'T')", (bid,)
    ).lastrowid
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (?, 'body', 'long')", (aid,)
    )
    conn.commit()


# --- discover.undrafted_brokers ---------------------------------------------


def test_undrafted_brokers_excludes_unprofiled_and_already_drafted(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    a = _broker(conn, "a.invalid")   # profiled, no draft -> included
    b = _broker(conn, "b.invalid")   # not profiled -> excluded
    c = _broker(conn, "c.invalid")   # profiled and drafted -> excluded
    _profile(conn, a)
    _profile(conn, c)
    _drafted(conn, c)

    domains = [r["domain"] for r in discover.undrafted_brokers(conn, 10)]
    assert domains == ["a.invalid"]


def test_undrafted_brokers_respects_limit(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(5):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)
    assert len(discover.undrafted_brokers(conn, 2)) == 2


def test_undrafted_brokers_negative_limit_is_unbounded_in_sqlite(tmp_path):
    """The mechanism the CLI guard exists to stop, asserted directly (mirrors C2)."""
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(12):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)
    assert len(discover.undrafted_brokers(conn, -1)) == 12


# --- cli.cmd_draft: ceiling ---------------------------------------------------


def test_draft_refuses_a_limit_over_the_ceiling(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS + 1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_draft_refuses_a_negative_limit_and_builds_nothing(tmp_path, capsys, monkeypatch):
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(12):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)

    def _boom(*a, **k):
        raise AssertionError("no client should be constructed on refusal")

    monkeypatch.setattr(cli, "AngleClient", _boom)
    monkeypatch.setattr(cli, "DraftClient", _boom)

    rc = cli.cmd_draft(path, limit=-1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0


def test_draft_refuses_a_zero_limit(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_draft(path, limit=0)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_draft_ceiling_refusal_explains_three_calls_per_broker(tmp_path, capsys):
    path = _db(tmp_path)
    cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS + 1)
    out = capsys.readouterr().out.lower()
    assert "three" in out
    assert "call" in out


def test_draft_at_the_ceiling_is_allowed(tmp_path):
    path = _db(tmp_path)
    # No profiled-but-undrafted brokers, so nothing is drafted and no API
    # client is built (would otherwise need ANTHROPIC_API_KEY).
    assert cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS) == 0


def test_draft_with_nothing_to_do_prints_a_message(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_draft(path) == 0
    assert "no" in capsys.readouterr().out.lower()


# --- cli.cmd_draft: happy path, with fake clients (no network / API key) -----


class _FakeAngleClient:
    def __init__(self):
        self.calls = 0

    def propose(self, profile, broker_name):
        self.calls += 1
        return [
            {
                "title": "An angle",
                "premise": "p",
                "audience_value": "v",
                "sunreef_relevance": "r",
                "score": 0.7,
            }
        ]


class _FakeDraftClient:
    def write_long(self, angle, profile, broker_name):
        return "Long body."

    def write_short(self, long_body, profile):
        return "Short body."


def test_draft_drives_undrafted_brokers_and_prints_a_line_per_broker(
    tmp_path, capsys, monkeypatch
):
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid", "Acme")
    _profile(conn, bid)

    monkeypatch.setattr(cli, "AngleClient", _FakeAngleClient)
    monkeypatch.setattr(cli, "DraftClient", _FakeDraftClient)

    rc = cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS)
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.invalid" in out

    conn = db.connect(path)
    drafts = conn.execute("SELECT format, status FROM draft").fetchall()
    assert {d["format"] for d in drafts} == {"long", "short"}
    assert all(d["status"] == "pending_review" for d in drafts)


def test_main_dispatches_draft(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "draft", "--limit", "1"]) == 0
