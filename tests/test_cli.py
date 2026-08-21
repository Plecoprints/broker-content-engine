from bce import cli, db, discover


def test_init_creates_schema(tmp_path):
    p = tmp_path / "t.db"
    assert cli.cmd_init(str(p)) == 0
    conn = db.connect(str(p))
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "broker" in names


def test_import_respects_volume_cap(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    rows = "name,domain\n" + "".join(
        f"B{i},b{i}.com\n" for i in range(cli.MAX_BROKERS + 5)
    )
    csv_file = tmp_path / "in.csv"
    csv_file.write_text(rows)
    rc = cli.cmd_import(str(p), str(csv_file))
    assert rc == 1
    assert "cap" in capsys.readouterr().out.lower()
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 0


def test_import_under_cap_succeeds(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("name,domain\nAcme,acme.com\n")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_list_prints_broker(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nAcme,acme.com\n")
    assert cli.cmd_list(str(p)) == 0
    assert "Acme" in capsys.readouterr().out


def test_main_returns_2_with_no_command():
    assert cli.main([]) == 2


def test_import_at_exact_cap_succeeds(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    rows = "name,domain\n" + "".join(
        f"B{i},b{i}.com\n" for i in range(cli.MAX_BROKERS)
    )
    csv_file.write_text(rows)
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == cli.MAX_BROKERS


def test_import_one_over_cap_refuses(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    rows = "name,domain\n" + "".join(
        f"B{i},b{i}.com\n" for i in range(cli.MAX_BROKERS + 1)
    )
    csv_file.write_text(rows)
    rc = cli.cmd_import(str(p), str(csv_file))
    assert rc == 1
    assert "cap" in capsys.readouterr().out.lower()
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 0


def test_import_missing_csv_file_returns_1(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    rc = cli.cmd_import(str(p), "/nonexistent/path/file.csv")
    assert rc == 1
    output = capsys.readouterr().out
    assert "not found" in output.lower() or "error" in output.lower()


def test_import_csv_with_quoted_newline(tmp_path):
    """CSV with a quoted field containing a newline should count correctly."""
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    # CSV with a quoted field containing an embedded newline
    csv_content = 'name,domain\nAcme,"acme.com\nand more notes"\n'
    csv_file.write_text(csv_content)
    # csv.DictReader correctly parses this as 1 row (not 2 lines)
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    # Should have 1 broker, not be refused
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_unqualified_brokers_filters_correctly(tmp_path):
    """unqualified_brokers returns only unqualified brokers, respects limit."""
    p = tmp_path / "t.db"
    db.connect(str(p))
    db.init_schema(db.connect(str(p)))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nA,a.com\nB,b.com\nC,c.com\n")

    # All should be unqualified initially
    rows = discover.unqualified_brokers(conn, limit=10)
    assert len(rows) == 3

    # Test limit
    rows = discover.unqualified_brokers(conn, limit=2)
    assert len(rows) == 2

    # Mark one as qualified
    broker_id = conn.execute("SELECT id FROM broker WHERE name = 'A'").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified = 1 WHERE id = ?", (broker_id,))
    conn.commit()

    # Should now return 2 unqualified
    rows = discover.unqualified_brokers(conn, limit=10)
    assert len(rows) == 2
    assert all(r["domain"] in ("b.com", "c.com") for r in rows)
