"""Test draft schema additions for Stage 3 follow-ups."""
import sqlite3
import pytest
from bce import db


def test_init_schema_creates_draft_columns():
    """The six draft columns exist after init_schema."""
    conn = db.connect(":memory:")
    db.init_schema(conn)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
    draft_columns = {"format", "passes_uniqueness", "max_similarity",
                     "most_similar_draft_id", "passes_originality", "embedding"}
    assert draft_columns <= cols, f"Missing: {draft_columns - cols}"


def test_init_schema_creates_draft_asset_table():
    """The draft_asset table exists after init_schema, and matches spec §8
    exactly: draft_asset(draft_id, asset_id, provider, usage_rights_confirmed).

    A presence-only check (F5) would have passed against the old, wrong
    shape -- `draft_asset(id, draft_id, asset_type, asset_url, metadata,
    created_at)` -- which shares no column with the spec beyond `draft_id`
    and silently dropped `usage_rights_confirmed`, the column §10.7 requires.
    """
    conn = db.connect(":memory:")
    db.init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='draft_asset'"
    ).fetchall()
    assert len(rows) == 1, "draft_asset table must exist"

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft_asset)")}
    assert cols == {"draft_id", "asset_id", "provider", "usage_rights_confirmed"}, (
        f"draft_asset must match spec section 8 exactly, got {cols}"
    )


def test_init_schema_migrates_an_old_shaped_draft_asset_table():
    """A database built before F5's fix keeps its old draft_asset columns
    (nothing reads or writes them) but gains the three correct ones.
    """
    conn = db.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE draft_asset (
            id                INTEGER PRIMARY KEY,
            draft_id          INTEGER NOT NULL,
            asset_type        TEXT,
            asset_url         TEXT,
            metadata          TEXT,
            created_at        TEXT
        );
        """
    )
    conn.commit()

    added = db.init_schema(conn)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft_asset)")}
    assert {"asset_id", "provider", "usage_rights_confirmed"} <= cols
    assert "draft_asset.asset_id" in added
    assert "draft_asset.usage_rights_confirmed" in added


def test_schema_version_at_least_3():
    """SCHEMA_VERSION reached 3 (draft.format CHECK grew a table rebuild, per
    spec v0.6's three-format change -- SQLite cannot ALTER a CHECK in place,
    so this is a real shape change, not just an added column).

    Was `test_schema_version_bumped_to_3` asserting `== 3` exactly; loosened
    to `>= 3` because spec §5b/§8's keyword-targeting task bumped it again to
    4 (see test_db_keywords.py test_init_schema_migrates_an_old_shaped_
    database_gains_keyword_tables) -- pinning this test to the literal value 3
    would make it fail on every future bump for a reason unrelated to what it
    actually tests (the v2->v3 draft.format rebuild happened and is not lost).
    """
    assert db.SCHEMA_VERSION >= 3


def test_format_column_is_text():
    """format column stores TEXT values."""
    conn = db.connect(":memory:")
    db.init_schema(conn)

    # Insert a broker and angle first (required for draft FK)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Test', 'test.com', 'manual')"
    )
    conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (1, 'Test Angle')"
    )

    # Insert a draft with format value
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test body', 'long')"
    )

    row = conn.execute("SELECT format FROM draft").fetchone()
    assert row["format"] == "long"


def test_format_column_check_constraint_allows_long_medium_short():
    """format CHECK constraint allows exactly 'long', 'medium', 'short' (spec
    v0.6 §5/§8: three draft formats, not two).
    """
    conn = db.connect(":memory:")
    db.init_schema(conn)

    # Insert required parent rows
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Test', 'test.com', 'manual')"
    )
    conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (1, 'Test Angle')"
    )

    # All three valid values should work
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test', 'long')"
    )
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test', 'medium')"
    )
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test', 'short')"
    )

    # An invalid value should still fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test2', 'huge')"
        )


def test_init_schema_migrates_older_database_with_draft_columns():
    """Old database without draft columns gains them on init_schema."""
    # Create old schema without draft columns
    conn = db.connect(":memory:")
    conn.executescript("""
        CREATE TABLE draft (
            id                            INTEGER PRIMARY KEY,
            angle_id                      INTEGER NOT NULL,
            body_md                       TEXT NOT NULL,
            word_count                    INTEGER,
            sunreef_mentions              INTEGER,
            passes_editorial_value_test   INTEGER,
            status                        TEXT NOT NULL DEFAULT 'pending_review'
        );
    """)
    conn.commit()

    # Run init_schema to add the columns
    added = db.init_schema(conn)

    # Check that columns were added
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
    assert "format" in cols
    assert "passes_uniqueness" in cols
    assert "passes_originality" in cols

    # Check migration recorded the additions
    added_names = [f for f in added if f.startswith("draft.")]
    assert len(added_names) >= 6, f"Should add 6 draft columns, got {added_names}"


# --- v0.6: draft.format CHECK rebuild ('long', 'short') -> ('long', 'medium',
# --- 'short'). SQLite has no ALTER TABLE ... ALTER CHECK, so a database
# --- already carrying the two-value CHECK (SCHEMA_VERSION 2 shape) needs a
# --- full table rebuild, not an additive ALTER TABLE ADD COLUMN. ------------

# The exact v2 draft table shape (format CHECK allows only 'long'/'short'),
# alongside the other tables a real v2 database would already have, so the
# migration is exercised against a realistic file rather than an isolated
# `draft` table.
_V2_SCHEMA = """
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
    has_editorial     INTEGER,
    has_newsletter    INTEGER,
    newsletter_evidence TEXT,
    editorial_last_post TEXT,
    qualified         INTEGER,
    qualified_reason  TEXT,
    robots_allowed    INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE angle (
    id               INTEGER PRIMARY KEY,
    broker_id        INTEGER NOT NULL REFERENCES broker(id),
    title            TEXT NOT NULL,
    premise          TEXT,
    audience_value   TEXT,
    sunreef_relevance TEXT,
    score            REAL,
    rejected_reason  TEXT
);

CREATE TABLE draft (
    id                            INTEGER PRIMARY KEY,
    angle_id                      INTEGER NOT NULL REFERENCES angle(id),
    body_md                       TEXT NOT NULL,
    word_count                    INTEGER,
    sunreef_mentions              INTEGER,
    passes_editorial_value_test   INTEGER,
    status                        TEXT NOT NULL DEFAULT 'pending_review'
                                  CHECK (status IN ('pending_review', 'approved',
                                         'rejected', 'sent', 'published', 'declined')),
    reviewed_by                   TEXT,
    reviewed_at                   TEXT,
    reviewer_edits                TEXT,
    format                        TEXT CHECK (format IN ('long', 'short')),
    passes_uniqueness             INTEGER,
    max_similarity                REAL,
    most_similar_draft_id         INTEGER,
    passes_originality            INTEGER,
    embedding                     TEXT
);

CREATE TABLE outcome (
    draft_id          INTEGER PRIMARY KEY REFERENCES draft(id),
    sent_at           TEXT,
    response          TEXT,
    published_url     TEXT,
    utm_campaign      TEXT,
    referral_sessions INTEGER,
    inquiries INTEGER
);

CREATE TABLE draft_asset (
    draft_id                INTEGER NOT NULL REFERENCES draft(id),
    asset_id                TEXT,
    provider                TEXT,
    usage_rights_confirmed  INTEGER
);
"""


def _seed_v2_database(conn: sqlite3.Connection) -> int:
    """A v2-shaped database with one broker/angle/draft already on disk.
    Returns the draft id, so the migration test can prove that exact row
    survives the rebuild untouched."""
    conn.executescript(_V2_SCHEMA)
    conn.execute(f"PRAGMA user_version = 2")
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Old Yachts', 'old.com', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'Old Angle')")
    cursor = conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
        "VALUES (1, 'Pre-existing long body.', 4, 'pending_review', 'long')"
    )
    conn.commit()
    return cursor.lastrowid


def test_init_schema_migrates_a_v2_draft_table_to_allow_medium():
    """The core claim: a database built before the three-format change
    upgrades in place, and 'medium' becomes insertable afterward.
    """
    conn = db.connect(":memory:")
    draft_id = _seed_v2_database(conn)

    db.init_schema(conn)

    # The CHECK constraint on disk now allows 'medium'.
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='draft'"
    ).fetchone()["sql"]
    assert "medium" in sql

    # The pre-existing row survived the rebuild with its data intact.
    row = conn.execute("SELECT * FROM draft WHERE id=?", (draft_id,)).fetchone()
    assert row is not None
    assert row["body_md"] == "Pre-existing long body."
    assert row["format"] == "long"
    assert row["status"] == "pending_review"

    # 'medium' is now insertable...
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'A medium post.', 'medium')"
    )
    got = conn.execute(
        "SELECT format FROM draft WHERE body_md='A medium post.'"
    ).fetchone()
    assert got["format"] == "medium"

    # ...while the CHECK constraint still rejects garbage.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'x', 'huge')"
        )

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_init_schema_draft_rebuild_preserves_foreign_key_references():
    """`outcome` and `draft_asset` both reference draft(id) via FK; the
    rebuild (rename/recreate/copy/drop) must not corrupt those references.
    """
    conn = db.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    draft_id = _seed_v2_database(conn)
    conn.execute(
        "INSERT INTO outcome (draft_id, response) VALUES (?, 'no reply yet')",
        (draft_id,),
    )
    conn.commit()

    db.init_schema(conn)

    row = conn.execute(
        "SELECT * FROM outcome WHERE draft_id=?", (draft_id,)
    ).fetchone()
    assert row is not None
    assert row["response"] == "no reply yet"


def test_init_schema_draft_rebuild_is_idempotent():
    """Running init_schema again after the rebuild must not rebuild a second
    time or duplicate rows (mirrors `test_init_schema_adds_nothing_to_a_current_database`).
    """
    conn = db.connect(":memory:")
    _seed_v2_database(conn)
    db.init_schema(conn)
    before = conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"]

    added = db.init_schema(conn)

    after = conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"]
    assert after == before
    assert added == []
