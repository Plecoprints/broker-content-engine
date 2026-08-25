import json

from bce import cli, db, discover, profile


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


# --- C2: SQLite reads a negative LIMIT as unbounded --------------------------

def _thirty_five_qualified(path):
    conn = db.connect(path)
    discover.import_csv(
        conn, "name,domain\n" + "".join(f"B{i},b{i}.invalid\n" for i in range(35))
    )
    conn.execute("UPDATE broker SET qualified=1")
    conn.commit()
    return conn


def test_negative_limit_would_be_unbounded_in_sqlite(tmp_path):
    """The mechanism the CLI guard exists to stop, asserted directly."""
    path = _db(tmp_path)
    conn = _thirty_five_qualified(path)
    assert len(discover.unprofiled_brokers(conn, 20)) == 20
    assert len(discover.unprofiled_brokers(conn, -1)) == 35


def test_profile_refuses_a_negative_limit_and_builds_nothing(tmp_path, capsys):
    path = _db(tmp_path)
    _thirty_five_qualified(path)
    # No ANTHROPIC_API_KEY is needed: the refusal must return before Fetcher()
    # and ProfileClient() are constructed.
    rc = cli.cmd_profile(path, limit=-1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 0


def test_profile_refuses_a_zero_limit(tmp_path, capsys):
    path = _db(tmp_path)
    _thirty_five_qualified(path)
    assert cli.cmd_profile(path, limit=0) == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_profile_at_limit_one_is_allowed(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_profile(path, limit=1) == 0
    assert "no qualified brokers" in capsys.readouterr().out


# --- I5: silent degradation must not print as success ------------------------

def test_profile_label_distinguishes_a_statistics_only_row():
    assert cli._profile_label(profile.ProfileResult(True, True)) == "profiled"
    degraded = cli._profile_label(profile.ProfileResult(True, False))
    assert "classification failed" in degraded
    assert cli._profile_label(profile.ProfileResult(False)) == "no articles found"


# --- I6: warmest first (spec §4) ---------------------------------------------

def test_unprofiled_brokers_orders_warmest_first(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(
        conn,
        "name,domain\n"
        "Zulu,zulu.invalid\n"      # lists_inventory — coldest name, warmest signal
        "Alpha,alpha.invalid\n"    # none
        "Mike,mike.invalid\n"      # mentions
        "Bravo,bravo.invalid\n"    # unknown
        "Yankee,yankee.invalid\n"  # lists_inventory
    )
    conn.execute("UPDATE broker SET qualified=1")
    for domain, affinity in [
        ("zulu.invalid", "lists_inventory"),
        ("alpha.invalid", "none"),
        ("mike.invalid", "mentions"),
        ("bravo.invalid", "unknown"),
        ("yankee.invalid", "lists_inventory"),
    ]:
        conn.execute(
            "UPDATE broker SET sunreef_affinity=? WHERE domain=?", (affinity, domain)
        )
    conn.commit()

    domains = [r["domain"] for r in discover.unprofiled_brokers(conn, 10)]
    assert domains == [
        "yankee.invalid",  # lists_inventory, name-sorted within the band
        "zulu.invalid",
        "mike.invalid",    # mentions
        "alpha.invalid",   # everything else, name-sorted
        "bravo.invalid",
    ]
    # Ordering only: every qualified broker is still returned (spec §2, §4).
    assert len(domains) == 5


def test_unprofiled_brokers_returns_every_broker_regardless_of_affinity(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\n")
    conn.execute("UPDATE broker SET qualified=1, sunreef_affinity='none'")
    conn.commit()
    assert len(discover.unprofiled_brokers(conn, 10)) == 2


# --- I3: a degraded profile can be repaired ----------------------------------

def _profiled(conn, domain, register):
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, themes) VALUES (?,?,?)",
        (bid, register, json.dumps([])),
    )
    conn.commit()


def test_reprofile_clears_only_degraded_rows(tmp_path, capsys):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\n")
    conn.execute("UPDATE broker SET qualified=1")
    conn.commit()
    _profiled(conn, "a.invalid", None)             # classify() returned {}
    _profiled(conn, "b.invalid", "warm professional")

    assert cli.cmd_reprofile(path) == 0
    assert "cleared 1" in capsys.readouterr().out
    conn = db.connect(path)
    domains = [r["domain"] for r in discover.unprofiled_brokers(conn, 10)]
    assert domains == ["a.invalid"]


def test_reprofile_one_domain_clears_a_good_row_too(tmp_path, capsys):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\n")
    conn.execute("UPDATE broker SET qualified=1")
    conn.commit()
    _profiled(conn, "a.invalid", "warm professional")

    assert cli.cmd_reprofile(path, "https://www.a.invalid/") == 0
    assert "cleared 1" in capsys.readouterr().out
    conn = db.connect(path)
    assert [r["domain"] for r in discover.unprofiled_brokers(conn, 10)] == ["a.invalid"]


def test_reprofile_unknown_domain_returns_1(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_reprofile(path, "nope.invalid") == 1
    assert "no voice profile found" in capsys.readouterr().out


def test_reprofile_with_nothing_degraded_returns_0(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_reprofile(path) == 0
    assert "no degraded voice profiles" in capsys.readouterr().out


def test_main_routes_reprofile(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "reprofile"]) == 0
