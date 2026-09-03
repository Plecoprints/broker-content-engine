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


# --- Residual A3: cmd_list must surface channel state -------------------------

def test_list_shows_channel_state_and_editorial_date(tmp_path, capsys):
    """An operator must be able to tell 'no channel' apart from 'we could not
    date the channel' — both cases previously printed identically because
    cmd_list dropped has_editorial/has_newsletter/editorial_last_post."""
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nAcme,acme.com\nBeta,beta.com\n")
    conn.execute(
        "UPDATE broker SET qualified=0, qualified_reason='editorial_recency_undetermined', "
        "has_editorial=0, has_newsletter=0, editorial_last_post='unknown' "
        "WHERE domain='acme.com'"
    )
    conn.execute(
        "UPDATE broker SET qualified=1, qualified_reason='passed', "
        "has_editorial=1, has_newsletter=0, editorial_last_post='2026-05-01' "
        "WHERE domain='beta.com'"
    )
    conn.commit()

    assert cli.cmd_list(str(p)) == 0
    out = capsys.readouterr().out
    lines = {ln.split()[0]: ln for ln in out.splitlines()}

    # Acme: editorial link found but undated -> distinguishable from "no channel".
    assert "editorial=no" in lines["Acme"]
    assert "unknown" in lines["Acme"]

    # Beta: editorial dated and fresh -> the actual date is shown.
    assert "editorial=yes" in lines["Beta"]
    assert "2026-05-01" in lines["Beta"]

    # Every broker list_brokers returns still prints, regardless of affinity.
    assert "Acme" in out and "Beta" in out


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
    """CSV with a quoted field containing a newline should count correctly.

    The embedded newline moved from the domain cell to the name cell: a domain
    cell of "acme.com\\nand more notes" is not a hostname and is now rejected
    by normalization (I5), which would hide what this test is about — that
    csv.DictReader counts this as one row, not two.
    """
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_content = 'name,domain\n"Acme\nBrokerage",acme.com\n'
    csv_file.write_text(csv_content)
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    # Should have 1 broker, not be refused
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


# --- I3: header variants must not import silently as zero rows ---------------

def test_import_accepts_capitalized_headers(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("Name,Domain\nAcme,acme.com\n")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    assert "imported 1 brokers" in capsys.readouterr().out
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_import_accepts_excel_utf8_bom(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("name,domain\nAcme,acme.com\n", encoding="utf-8-sig")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_import_accepts_space_after_comma_in_header(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("name, domain\nAcme,acme.com\n")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_import_wrong_headers_fails_loudly(tmp_path, capsys):
    """A CSV with no name/domain column must not look like an empty import."""
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("company,website\nAcme,acme.com\n")
    rc = cli.cmd_import(str(p), str(csv_file))
    out = capsys.readouterr().out
    assert rc == 1
    assert "company" in out and "website" in out
    assert "imported" not in out


def test_import_warns_about_unusable_domain_cell(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("name,domain\nGood,acme.com\nBad,call me for the site\n")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    out = capsys.readouterr().out
    assert "call me for the site" in out
    assert "imported 1 brokers" in out


# --- I4: the cap counts new brokers, not CSV rows ---------------------------

def test_reimporting_the_master_list_plus_one_is_not_capped(tmp_path, capsys):
    """A cumulative master list must stay importable (spec §5 Stage 1)."""
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    master = "name,domain\n" + "".join(f"B{i},b{i}.com\n" for i in range(30))
    first = tmp_path / "master.csv"
    first.write_text(master)
    assert cli.cmd_import(str(p), str(first)) == 0

    second = tmp_path / "master2.csv"
    second.write_text(master + "New,new.com\n")
    rc = cli.cmd_import(str(p), str(second))
    out = capsys.readouterr().out
    assert rc == 0, out
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 31


def test_cap_still_refuses_and_inserts_nothing_when_all_rows_are_new(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    seed = tmp_path / "seed.csv"
    seed.write_text("name,domain\n" + "".join(f"S{i},s{i}.com\n" for i in range(40)))
    assert cli.cmd_import(str(p), str(seed)) == 0

    more = tmp_path / "more.csv"
    more.write_text("name,domain\n" + "".join(f"M{i},m{i}.com\n" for i in range(11)))
    rc = cli.cmd_import(str(p), str(more))
    assert rc == 1
    assert "cap" in capsys.readouterr().out.lower()
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 40


# --- I5: requalify -----------------------------------------------------------

def test_requalify_one_domain_clears_the_verdict(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nAcme,acme.com\n")
    conn.execute(
        "UPDATE broker SET qualified=0, qualified_reason='unreachable_or_disallowed'"
    )
    conn.commit()

    assert cli.cmd_requalify(str(p), "https://www.acme.com/") == 0
    assert "cleared 1" in capsys.readouterr().out
    conn = db.connect(str(p))
    assert len(discover.unqualified_brokers(conn, limit=10)) == 1


def test_requalify_all_rejected(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nA,a.com\nB,b.com\n")
    conn.execute("UPDATE broker SET qualified=0")
    conn.commit()
    assert cli.cmd_requalify(str(p)) == 0
    conn = db.connect(str(p))
    assert len(discover.unqualified_brokers(conn, limit=10)) == 2


def test_requalify_unknown_domain_returns_1(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    assert cli.cmd_requalify(str(p), "nope.com") == 1
    assert "no broker found" in capsys.readouterr().out


def test_main_routes_requalify(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    assert cli.main(["--db", str(p), "requalify"]) == 0


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


# =============================================================================
# `qualify` must not let a rendering failure read as a fact about the broker
# =============================================================================

class _ShellFetcher:
    """A client-rendered site: 200 OK, and an empty app shell."""

    def robots_allows(self, url):
        return True

    def get(self, url):
        return "<html><body><div id=\"root\"></div></body></html>"


class _RichFetcher:
    """A server-rendered brokerage page with real content."""

    def robots_allows(self, url):
        return True

    def get(self, url):
        return (
            "<html><body><p>"
            + ("We broker sailing catamarans from 60 ft to 90 ft. " * 40)
            + "</p></body></html>"
        )


def _one_broker(tmp_path, domain="spa.invalid"):
    from bce import db, discover

    path = str(tmp_path / "q.db")
    conn = db.connect(path)
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nT,{domain}\n")
    conn.commit()
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.close()
    return path, bid


def test_an_unreadable_page_is_flagged_not_taken_at_face_value(tmp_path, capsys):
    """A client-rendered site yields no visible text, so every detector reads an
    empty page and the broker is recorded `below_length_threshold` -- which
    reads as "too small for us" when the truth is "we could not see the page".
    Spec §7 lists Playwright for these sites and it is not built, so the only
    honest handling is to say so loudly.
    """
    from bce import db, qualify

    path, bid = _one_broker(tmp_path)
    conn = db.connect(path)
    verdict = qualify.qualify_broker(conn, bid, _ShellFetcher())

    assert verdict["qualified"] is False
    assert verdict["render_suspect"] is True
    assert verdict["visible_text_chars"] < qualify.RENDER_SUSPICION_CHARS


def test_a_readable_page_is_never_flagged_as_a_rendering_problem(tmp_path):
    from bce import db, qualify

    path, bid = _one_broker(tmp_path, domain="rich.invalid")
    conn = db.connect(path)
    verdict = qualify.qualify_broker(conn, bid, _RichFetcher())
    assert verdict["render_suspect"] is False
    assert verdict["visible_text_chars"] > qualify.RENDER_SUSPICION_CHARS


def test_a_qualified_broker_is_never_render_suspect(tmp_path):
    """`render_suspect` exists to explain a rejection. A pass needs no excuse,
    so the flag must never ride along on one."""
    from bce import db, qualify

    path, bid = _one_broker(tmp_path, domain="ok.invalid")
    conn = db.connect(path)
    verdict = qualify.qualify_broker(conn, bid, _RichFetcher())
    if verdict["qualified"]:
        assert verdict["render_suspect"] is False
