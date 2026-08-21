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
