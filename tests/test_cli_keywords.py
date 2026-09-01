"""CLI wiring for `bce keywords <csv>` (spec §5b), mirroring `cmd_import`'s
style: db path resolution via `db.connect`/`db.init_schema`, a `--db`-scoped
subcommand, and rc=1 with a printed `error:` line on a bad input rather than
an exception or a silent zero-row import.
"""
from bce import cli, db

DATA_CSV = "data/keyword_bank.csv"
FIXTURES = "tests/fixtures/keyword_exports"


def _db(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    return str(p)


def test_keywords_loads_the_committed_bank_and_reports_the_split(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, DATA_CSV)
    assert rc == 0
    out = capsys.readouterr().out
    assert "loaded 62 keywords" in out
    assert "62 qualify" in out
    assert "0 do not" in out

    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"] == 62


def test_keywords_reports_qualify_split_and_missed_thresholds(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, f"{FIXTURES}/bom_semicolon_thousands.csv")
    assert rc == 0
    out = capsys.readouterr().out
    assert "3 qualify" in out
    assert "2 do not" in out
    assert "missed on difficulty" in out
    assert "2 missed on difficulty" in out
    assert "0 missed on volume" in out


def test_keywords_reports_skipped_rows_and_why(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, f"{FIXTURES}/malformed_rows.csv")
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped 2" in out
    assert "volume" in out
    assert "difficulty" in out


def test_keywords_missing_csv_file_returns_1(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, "/nonexistent/path/keywords.csv")
    assert rc == 1
    out = capsys.readouterr().out
    assert "not found" in out.lower() or "error" in out.lower()


def test_keywords_bad_header_returns_1(tmp_path, capsys):
    path = _db(tmp_path)
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text("Domain,Traffic,Rank\nacme.com,1000,5\n")
    rc = cli.cmd_keywords(path, str(csv_file))
    assert rc == 1
    out = capsys.readouterr().out
    assert "error" in out.lower()


def test_keywords_is_idempotent_via_cli(tmp_path, capsys):
    path = _db(tmp_path)
    cli.cmd_keywords(path, DATA_CSV)
    capsys.readouterr()
    rc = cli.cmd_keywords(path, DATA_CSV)
    assert rc == 0
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"] == 62


def test_main_routes_keywords(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "keywords", DATA_CSV]) == 0


# --- report gains the segment-relevance and editorial-intent dimensions -----


def test_keywords_reports_segment_relevance_split_and_reasons(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, "data/semrush-us-2026-09-01.csv")
    assert rc == 0
    out = capsys.readouterr().out
    assert "segment relevance" in out.lower()
    assert "relevant" in out
    assert "excluded" in out
    assert "not_a_boat" in out
    assert "monthly volume" in out


def test_keywords_reports_editorial_intent_split(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_keywords(path, "data/semrush-us-2026-09-01.csv")
    assert rc == 0
    out = capsys.readouterr().out
    assert "editorial intent" in out.lower()
    assert "not editorial" in out.lower()
