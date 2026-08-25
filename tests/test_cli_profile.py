from bce import cli, db, discover


def _db(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    return str(p)


def test_unprofiled_brokers_excludes_unqualified_and_already_profiled(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\nC,c.invalid\n")
    conn.execute("UPDATE broker SET qualified=1 WHERE domain IN ('a.invalid','b.invalid')")
    conn.execute("UPDATE broker SET qualified=0 WHERE domain='c.invalid'")
    bid = conn.execute("SELECT id FROM broker WHERE domain='b.invalid'").fetchone()["id"]
    conn.execute("INSERT INTO voice_profile (broker_id) VALUES (?)", (bid,))
    conn.commit()
    domains = [r["domain"] for r in discover.unprofiled_brokers(conn, 10)]
    assert domains == ["a.invalid"]


def test_unprofiled_brokers_respects_limit(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\n")
    conn.execute("UPDATE broker SET qualified=1")
    conn.commit()
    assert len(discover.unprofiled_brokers(conn, 1)) == 1


def test_profile_refuses_a_limit_over_the_ceiling(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_profile(path, limit=cli.MAX_PROFILE_CALLS + 1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_profile_at_the_ceiling_is_allowed(tmp_path):
    path = _db(tmp_path)
    # No qualified brokers, so nothing is profiled and no API client is built.
    assert cli.cmd_profile(path, limit=cli.MAX_PROFILE_CALLS) == 0


def test_main_dispatches_profile(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "profile", "--limit", "1"]) == 0
