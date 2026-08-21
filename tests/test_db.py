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


def test_broker_has_channel_columns():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(broker)")}
    assert {"has_editorial", "has_newsletter", "newsletter_evidence"} <= cols


def test_init_schema_stamps_user_version():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert db.SCHEMA_VERSION >= 1


# The pre-Task-5b broker table: no channel columns, no editorial_last_post.
_OLD_BROKER_SCHEMA = """
CREATE TABLE broker (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    domain            TEXT NOT NULL UNIQUE,
    region            TEXT,
    segment_evidence  TEXT,
    source            TEXT NOT NULL CHECK (source IN ('discovered', 'manual')),
    sunreef_affinity  TEXT NOT NULL DEFAULT 'unknown'
                      CHECK (sunreef_affinity IN
                             ('none', 'mentions', 'lists_inventory', 'unknown')),
    affinity_evidence TEXT,
    qualified         INTEGER,
    qualified_reason  TEXT,
    robots_allowed    INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def test_init_schema_migrates_an_older_database():
    """CREATE TABLE IF NOT EXISTS never adds a column; the migration must.

    Reproduces the trap: a DB created before the channel columns existed used
    to survive init_schema unchanged, and qualification then died with
    'no such column: has_editorial'.
    """
    conn = db.connect(":memory:")
    conn.executescript(_OLD_BROKER_SCHEMA)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Old', 'old.com', 'manual')"
    )
    conn.commit()

    added = db.init_schema(conn)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(broker)")}
    assert {
        "has_editorial", "has_newsletter", "newsletter_evidence",
        "editorial_last_post",
    } <= cols
    assert "broker.has_editorial" in added
    # existing data survives the upgrade
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    # and the new columns are readable
    assert conn.execute("SELECT has_editorial FROM broker").fetchone()[0] is None


def test_init_schema_adds_nothing_to_a_current_database():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    assert db.init_schema(conn) == []


def test_init_schema_refuses_a_newer_schema_version():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 7}")
    try:
        db.init_schema(conn)
        raised = None
    except db.SchemaTooNewError as exc:
        raised = str(exc)
    assert raised is not None
    assert str(db.SCHEMA_VERSION + 7) in raised
    assert str(db.SCHEMA_VERSION) in raised
