"""Schema support for the three originality gates (spec §10.3):

- `draft` gains `passes_tailored` / `tailored_score` (Gate 2 has no column
  in the spec §8 data model as written -- `passes_uniqueness` /
  `max_similarity` / `most_similar_draft_id` / `embedding` are Gate 1's,
  and `passes_originality` is already Gate 3's by name; Gate 2 needed new
  columns) and `originality_overlap` (Gate 3's collision figure, the
  containment-based counterpart to Gate 1's `max_similarity`).
- a new `source_fingerprint(broker_id, shingle_hash)` table, populated
  during profiling (see `test_profile.py`), which is what Gate 3 compares
  a draft against without ever storing recoverable prose (spec §10.3
  amendment -- see the spec doc and `bce.fingerprint`'s module docstring).

SCHEMA_VERSION bumps from 4 to 5, and a v4-shaped database (the shape
before this task) must migrate in place and keep its existing rows.
"""
import sqlite3

import pytest

from bce import db


def test_schema_version_covers_the_fingerprint_table():
    """`source_fingerprint` landed at version 5, so any database at 5 or later
    has it. Pinned to `== 5` originally, which made the assertion really about
    "nothing has changed since", and broke on the next unrelated bump (6, the
    `excluded_keyword` blocklist). What this test is actually for is that the
    version was raised far enough for §10.3's table to exist."""
    assert db.SCHEMA_VERSION >= 5


def test_source_fingerprint_table_exists_with_no_text_column():
    """The literal enforcement of spec §10.3's 'never full article text':
    the table has nowhere to put prose even if a caller tried.
    """
    conn = db.connect(":memory:")
    db.init_schema(conn)

    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='source_fingerprint'"
    ).fetchall()
    assert len(rows) == 1

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(source_fingerprint)")}
    assert cols == {"broker_id", "shingle_hash"}


def test_source_fingerprint_dedups_the_same_hash_for_a_broker():
    """A shingle recurring across articles (or a re-profile) must not
    duplicate rows -- the table is a *set* of hashes per broker.
    """
    conn = db.connect(":memory:")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('T', 't.invalid', 'manual')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) VALUES (1, 42)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) VALUES (1, 42)"
    )
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM source_fingerprint WHERE broker_id=1"
    ).fetchone()["c"]
    assert count == 1


def test_draft_gains_tailored_and_originality_overlap_columns():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
    assert {"passes_tailored", "tailored_score", "originality_overlap"} <= cols


# --- migration: a v4-shaped database (this task's starting point) ----------

_V4_DRAFT_TABLE = """
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
    format                        TEXT CHECK (format IN ('long', 'medium', 'short')),
    passes_uniqueness             INTEGER,
    max_similarity                REAL,
    most_similar_draft_id         INTEGER,
    passes_originality            INTEGER,
    embedding                     TEXT
);
"""


def _seed_v4_database(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE broker (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "domain TEXT NOT NULL UNIQUE, source TEXT NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE angle (id INTEGER PRIMARY KEY, broker_id INTEGER NOT NULL, "
        "title TEXT NOT NULL)"
    )
    conn.executescript(_V4_DRAFT_TABLE)
    conn.execute("PRAGMA user_version = 4")
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Old Yachts', 'old.invalid', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'Old Angle')")
    cursor = conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
        "VALUES (1, 'Pre-existing body.', 3, 'pending_review', 'long')"
    )
    conn.commit()
    return cursor.lastrowid


def test_init_schema_migrates_a_v4_database_and_keeps_its_rows():
    conn = db.connect(":memory:")
    draft_id = _seed_v4_database(conn)

    added = db.init_schema(conn)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
    assert {"passes_tailored", "tailored_score", "originality_overlap"} <= cols
    assert "draft.passes_tailored" in added
    assert "draft.tailored_score" in added
    assert "draft.originality_overlap" in added

    fingerprint_tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='source_fingerprint'"
    ).fetchall()
    assert len(fingerprint_tables) == 1

    # The pre-existing row survived untouched.
    row = conn.execute("SELECT * FROM draft WHERE id=?", (draft_id,)).fetchone()
    assert row["body_md"] == "Pre-existing body."
    assert row["format"] == "long"
    assert row["status"] == "pending_review"
    assert row["passes_tailored"] is None

    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_init_schema_migration_is_idempotent_for_v4():
    conn = db.connect(":memory:")
    _seed_v4_database(conn)
    db.init_schema(conn)

    added_again = db.init_schema(conn)

    assert added_again == []
