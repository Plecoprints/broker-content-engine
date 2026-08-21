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
