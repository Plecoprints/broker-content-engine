"""Schema for keyword targeting (spec §5b, §8): the `keyword` and
`draft_keyword` tables.

These are brand-new tables, not columns added to an existing one, so
`ADDITIVE_COLUMNS` (which only ALTERs existing tables) does not apply -- the
`CREATE TABLE IF NOT EXISTS` statements in `_SCHEMA` are what make an
old-shaped database (one built before this task) gain them cleanly. That is
the thing `test_init_schema_migrates_an_old_shaped_database_gains_keyword_tables`
below proves directly, mirroring the pattern in test_db.py /
test_db_draft.py's own migration tests.
"""
import sqlite3

import pytest

from bce import db


def _conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


# --- table existence and shape ----------------------------------------------


def test_init_schema_creates_keyword_and_draft_keyword_tables():
    conn = _conn()
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "keyword" in names
    assert "draft_keyword" in names


def test_keyword_table_matches_spec_section_8_shape():
    """keyword(id, phrase, volume, difficulty, intent, database, measured_at,
    qualifies, source) per spec §8, plus two columns not in the spec's own
    list but required by later changes to this same task:
    `competitor_brand` (spec §5b "Competitor brand terms" -- gates automatic
    selection of Sunreef's direct rivals) and `segment_relevant` /
    `segment_relevant_reason` (a second, independent gate: a keyword can
    clear the volume/difficulty thresholds and still not be about Sunreef's
    actual segment at all -- see keywords.classify_segment_relevance).
    """
    conn = _conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(keyword)")}
    spec_columns = {
        "id", "phrase", "volume", "difficulty", "intent", "database",
        "measured_at", "qualifies", "source",
    }
    assert spec_columns <= cols
    assert "competitor_brand" in cols
    assert "segment_relevant" in cols
    assert "segment_relevant_reason" in cols


def test_draft_keyword_table_matches_spec_section_8_shape():
    conn = _conn()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft_keyword)")}
    assert cols == {"draft_id", "keyword_id", "role"}


def test_schema_tables_lists_the_new_tables():
    assert "keyword" in db.SCHEMA_TABLES
    assert "draft_keyword" in db.SCHEMA_TABLES


# --- constraints -------------------------------------------------------------


def test_keyword_phrase_and_database_are_unique_together():
    """Spec §8: 'keyword.phrase + keyword.database unique together -- the
    same phrase has different metrics in different regional databases, so
    phrase alone is not the identity.'
    """
    conn = _conn()
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
    )
    conn.commit()
    # Same phrase, different database: allowed.
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 2900, 31, 'uk', 0)"
    )
    conn.commit()
    # Same phrase, same database again: rejected.
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
            "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
        )


def test_draft_keyword_role_check_constraint():
    conn = _conn()
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('T', 't.invalid', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'A')")
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'body', 'long')"
    )
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
    )
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 1, 'primary')"
    )
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 1, 'secondary')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 1, 'tertiary')"
        )


def test_exactly_one_primary_per_draft_enforced_by_partial_unique_index():
    """Spec §8: 'Exactly one primary per draft' -- enforced by a partial
    unique index (WHERE role='primary'), not application code, per the task
    brief. A second 'secondary' row for the same draft is fine; a second
    'primary' row is not.
    """
    conn = _conn()
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('T', 't.invalid', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'A')")
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'body', 'long')"
    )
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
    )
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamarans for sale', 4400, 24, 'us', 1)"
    )
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 1, 'primary')"
    )
    # Two secondaries for the same draft: fine, no uniqueness constraint on those.
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 2, 'secondary')"
    )
    conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 2, 'primary')"
        )


def test_two_different_drafts_can_each_have_their_own_primary():
    """The partial unique index is scoped per draft_id, not global."""
    conn = _conn()
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('T', 't.invalid', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'A')")
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'long body', 'long')"
    )
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'short body', 'short')"
    )
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
    )
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (1, 1, 'primary')"
    )
    # Draft 2 (a different draft) may also have a 'primary' row.
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (2, 1, 'primary')"
    )
    conn.commit()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM draft_keyword WHERE role='primary'"
    ).fetchone()["c"]
    assert count == 2


def test_keyword_qualifies_is_stored_not_recomputed():
    """Spec §8: qualifies is stored at import time. There must be no view or
    computed column silently overriding a stored 0 -- writing qualifies=0 for
    a keyword whose current volume/difficulty *would* pass today proves nothing
    recomputes it on read.
    """
    conn = _conn()
    # Volume/difficulty here would pass the §5b thresholds today, but the row
    # was stored with qualifies=0 (as if measured when it did not qualify) --
    # the column must return exactly what was written, not a live recomputation.
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, "
        "measured_at, qualifies, source) VALUES "
        "('catamaran for sale', 8100, 25, 'us', '2020-01-01', 0, 'semrush')"
    )
    conn.commit()
    row = conn.execute(
        "SELECT qualifies FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()
    assert row["qualifies"] == 0


# --- migration of an old-shaped database -------------------------------------


# The pre-Task-5b schema: no keyword or draft_keyword tables at all. Includes
# the rest of a realistic v3 database so the migration is exercised against a
# real file, not an isolated CREATE.
_PRE_KEYWORD_SCHEMA = """
CREATE TABLE broker (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    domain            TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL CHECK (source IN ('discovered', 'manual')),
    sunreef_affinity  TEXT NOT NULL DEFAULT 'unknown',
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE angle (
    id               INTEGER PRIMARY KEY,
    broker_id        INTEGER NOT NULL REFERENCES broker(id),
    title            TEXT NOT NULL
);

CREATE TABLE draft (
    id                            INTEGER PRIMARY KEY,
    angle_id                      INTEGER NOT NULL REFERENCES angle(id),
    body_md                       TEXT NOT NULL,
    status                        TEXT NOT NULL DEFAULT 'pending_review'
                                  CHECK (status IN ('pending_review', 'approved',
                                         'rejected', 'sent', 'published', 'declined')),
    format                        TEXT CHECK (format IN ('long', 'medium', 'short'))
);
"""


def test_init_schema_migrates_an_old_shaped_database_gains_keyword_tables():
    """The core migration proof: a database with no keyword/draft_keyword
    tables at all gains both, with existing data untouched, when init_schema
    runs against it.
    """
    conn = db.connect(":memory:")
    conn.executescript(_PRE_KEYWORD_SCHEMA)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Old Yachts', 'old.invalid', 'manual')"
    )
    conn.execute("INSERT INTO angle (broker_id, title) VALUES (1, 'Old Angle')")
    draft_id = conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (1, 'Pre-existing body.', 'long')"
    ).lastrowid
    conn.commit()

    names_before = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "keyword" not in names_before  # sanity: this really is the old shape

    db.init_schema(conn)

    names_after = {
        r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "keyword" in names_after
    assert "draft_keyword" in names_after

    # Pre-existing data survived the upgrade untouched.
    row = conn.execute("SELECT * FROM draft WHERE id=?", (draft_id,)).fetchone()
    assert row["body_md"] == "Pre-existing body."

    # The new tables are actually usable, not just present.
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies) "
        "VALUES ('catamaran for sale', 8100, 25, 'us', 1)"
    )
    conn.execute(
        "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?, 1, 'primary')",
        (draft_id,),
    )
    conn.commit()
    got = conn.execute(
        "SELECT role FROM draft_keyword WHERE draft_id=?", (draft_id,)
    ).fetchone()
    assert got["role"] == "primary"
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_init_schema_keyword_migration_is_idempotent():
    conn = db.connect(":memory:")
    conn.executescript(_PRE_KEYWORD_SCHEMA)
    conn.commit()
    db.init_schema(conn)
    before = conn.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='keyword'"
    ).fetchone()["c"]
    db.init_schema(conn)
    after = conn.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='keyword'"
    ).fetchone()["c"]
    assert before == after == 1
