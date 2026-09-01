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
    """The draft_asset table exists after init_schema."""
    conn = db.connect(":memory:")
    db.init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='draft_asset'"
    ).fetchall()
    assert len(rows) == 1, "draft_asset table must exist"


def test_schema_version_bumped_to_2():
    """SCHEMA_VERSION is incremented to 2."""
    assert db.SCHEMA_VERSION == 2


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


def test_format_column_check_constraint_rejects_invalid_values():
    """format CHECK constraint only allows 'long' or 'short'."""
    conn = db.connect(":memory:")
    db.init_schema(conn)

    # Insert required parent rows
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Test', 'test.com', 'manual')"
    )
    conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (1, 'Test Angle')"
    )

    # Valid values should work
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test', 'short')"
    )

    # Invalid value should fail
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Test2', 'medium')"
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
