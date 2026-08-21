import pytest

from bce import db, discover


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def test_import_csv_inserts_rows():
    conn = _conn()
    n = discover.import_csv(conn, "name,domain,region\nAcme,acme.com,Med\n")
    assert n == 1
    row = conn.execute("SELECT * FROM broker").fetchone()
    assert row["name"] == "Acme"
    assert row["domain"] == "acme.com"
    assert row["region"] == "Med"
    assert row["source"] == "manual"


def test_import_csv_skips_duplicate_domains():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\n")
    n = discover.import_csv(conn, "name,domain\nAcme Again,acme.com\n")
    assert n == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_import_csv_tolerates_missing_optional_region():
    conn = _conn()
    assert discover.import_csv(conn, "name,domain\nAcme,acme.com\n") == 1


def test_list_brokers_orders_by_affinity_then_name():
    conn = _conn()
    discover.import_csv(
        conn,
        "name,domain\nZulu,zulu.com\nAlpha,alpha.com\nBravo,bravo.com\n",
    )
    conn.execute("UPDATE broker SET sunreef_affinity='none' WHERE domain='alpha.com'")
    conn.execute(
        "UPDATE broker SET sunreef_affinity='lists_inventory' WHERE domain='zulu.com'"
    )
    conn.execute("UPDATE broker SET sunreef_affinity='mentions' WHERE domain='bravo.com'")
    names = [r["name"] for r in discover.list_brokers(conn)]
    assert names == ["Zulu", "Bravo", "Alpha"]


def test_list_brokers_filters_by_qualified():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\nBeta,beta.com\n")
    conn.execute("UPDATE broker SET qualified=1 WHERE domain='acme.com'")
    conn.execute("UPDATE broker SET qualified=0 WHERE domain='beta.com'")
    assert [r["name"] for r in discover.list_brokers(conn, qualified=True)] == ["Acme"]


def test_unqualified_brokers_filters_correctly():
    """unqualified_brokers returns only unqualified brokers, respects limit."""
    conn = _conn()
    discover.import_csv(conn, "name,domain\nA,a.com\nB,b.com\nC,c.com\n")

    # All should be unqualified initially
    rows = discover.unqualified_brokers(conn, limit=10)
    assert len(rows) == 3

    # Test limit
    rows = discover.unqualified_brokers(conn, limit=2)
    assert len(rows) == 2

    # Mark one as qualified
    broker_id = conn.execute("SELECT id FROM broker WHERE domain='a.com'").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (broker_id,))
    conn.commit()

    # Should now return 2 unqualified (excludes qualified ones)
    rows = discover.unqualified_brokers(conn, limit=10)
    assert len(rows) == 2
    domains = {r["domain"] for r in rows}
    assert domains == {"b.com", "c.com"}

    # Mark another as rejected
    broker_id = conn.execute("SELECT id FROM broker WHERE domain='b.com'").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=0 WHERE id=?", (broker_id,))
    conn.commit()

    # Should still return 1 unqualified (excludes rejected ones too)
    rows = discover.unqualified_brokers(conn, limit=10)
    assert len(rows) == 1
    assert rows[0]["domain"] == "c.com"


# --- I3: ordinary CSVs that used to import silently as zero rows -------------

@pytest.mark.parametrize("header", [
    "name,domain",
    "Name,Domain",
    "NAME,DOMAIN",
    "﻿name,domain",
    "name, domain",
    " name , domain ",
])
def test_import_csv_accepts_header_variants(header):
    conn = _conn()
    assert discover.import_csv(conn, f"{header}\nAcme,acme.com\n") == 1
    assert conn.execute("SELECT domain FROM broker").fetchone()["domain"] == "acme.com"


def test_import_csv_raises_on_missing_required_columns():
    conn = _conn()
    with pytest.raises(discover.CsvHeaderError) as excinfo:
        discover.import_csv(conn, "company,website\nAcme,acme.com\n")
    assert excinfo.value.found == ["company", "website"]
    assert "name" in str(excinfo.value) and "domain" in str(excinfo.value)


def test_import_csv_raises_on_empty_text():
    conn = _conn()
    with pytest.raises(discover.CsvHeaderError):
        discover.import_csv(conn, "")


# --- I5: domain normalization ------------------------------------------------

@pytest.mark.parametrize("cell,expected", [
    ("acme.com", "acme.com"),
    ("ACME.com", "acme.com"),
    ("  acme.com  ", "acme.com"),
    ("www.acme.com", "acme.com"),
    ("WWW.Acme.Com", "acme.com"),
    ("https://acme.com/", "acme.com"),
    ("http://www.acme.com/blog?utm=x", "acme.com"),
    ("//acme.com", "acme.com"),
    ("acme.com.", "acme.com"),
    ("acme.com:8443", "acme.com"),
    ("acme.co.uk", "acme.co.uk"),
])
def test_normalize_domain(cell, expected):
    assert discover.normalize_domain(cell) == expected


@pytest.mark.parametrize("cell", [
    "", "   ", "not a domain", "acme", "acme.com and more notes",
    "just some prose", "@@@",
])
def test_normalize_domain_rejects_non_hostnames(cell):
    assert discover.normalize_domain(cell) is None


def test_import_csv_normalizes_urls_and_www():
    conn = _conn()
    assert discover.import_csv(
        conn, "name,domain\nAcme,https://www.acme.com/about\n"
    ) == 1
    assert conn.execute("SELECT domain FROM broker").fetchone()["domain"] == "acme.com"


def test_www_and_bare_domain_are_one_broker():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\nAcme WWW,www.acme.com\n")
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_parse_rows_reports_unusable_domain_cells():
    rows, rejected = discover.parse_rows(
        "name,domain\nGood,acme.com\nBad,not a domain at all\n"
    )
    assert [r["domain"] for r in rows] == ["acme.com"]
    assert rejected == ["not a domain at all"]


# --- I4: the cap counts new brokers, not CSV rows ----------------------------

def test_count_new_domains_ignores_already_imported_brokers():
    conn = _conn()
    master = "name,domain\n" + "".join(f"B{i},b{i}.com\n" for i in range(30))
    discover.import_csv(conn, master)
    assert discover.count_new_domains(conn, master) == 0
    assert discover.count_new_domains(conn, master + "New,new.com\n") == 1


def test_count_new_domains_counts_a_repeated_domain_once():
    conn = _conn()
    assert discover.count_new_domains(
        conn, "name,domain\nA,dup.com\nB,https://www.dup.com/\n"
    ) == 1


# --- I5: requalify path ------------------------------------------------------

def test_clear_qualification_for_one_domain():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\nBeta,beta.com\n")
    conn.execute(
        "UPDATE broker SET qualified=0, qualified_reason='unreachable_or_disallowed'"
    )
    conn.commit()
    assert discover.clear_qualification(conn, domain="https://www.acme.com/") == 1
    pending = {r["domain"] for r in discover.unqualified_brokers(conn, limit=10)}
    assert pending == {"acme.com"}


def test_clear_qualification_clears_every_rejected_broker():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nA,a.com\nB,b.com\nC,c.com\n")
    conn.execute("UPDATE broker SET qualified=0 WHERE domain IN ('a.com','b.com')")
    conn.execute("UPDATE broker SET qualified=1 WHERE domain='c.com'")
    conn.commit()
    assert discover.clear_qualification(conn) == 2
    pending = {r["domain"] for r in discover.unqualified_brokers(conn, limit=10)}
    assert pending == {"a.com", "b.com"}
    # qualified brokers are untouched
    assert conn.execute(
        "SELECT qualified FROM broker WHERE domain='c.com'"
    ).fetchone()["qualified"] == 1


def test_clear_qualification_returns_zero_for_unknown_domain():
    conn = _conn()
    assert discover.clear_qualification(conn, domain="nope.com") == 0
