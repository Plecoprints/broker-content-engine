import sqlite3
from bce import db


def test_init_schema_creates_all_tables():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    for table in db.SCHEMA_TABLES:
        assert table in names


def test_init_schema_is_idempotent():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    db.init_schema(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='broker'"
    ).fetchone()["c"]
    assert count == 1


def test_broker_affinity_constraint_rejects_unknown_value():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    try:
        conn.execute(
            "INSERT INTO broker (name, domain, source, sunreef_affinity) "
            "VALUES ('X', 'x.com', 'manual', 'bogus')"
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised


def test_rows_are_mappings():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Acme', 'acme.com', 'manual')"
    )
    row = conn.execute("SELECT name FROM broker").fetchone()
    assert row["name"] == "Acme"
