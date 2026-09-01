"""SQLite store — single source of truth for pipeline state (spec §7, §8)."""
import sqlite3

SCHEMA_TABLES = ("broker", "voice_profile", "angle", "draft", "draft_asset", "outcome")

#: Bumped whenever the shape below changes. Stored in `PRAGMA user_version` so
#: an existing file can be recognised instead of silently keeping an old shape
#: (`CREATE TABLE IF NOT EXISTS` never adds a column to a table that exists).
SCHEMA_VERSION = 2

#: Columns added to already-created tables after their first release. Applied
#: additively by `init_schema` via ALTER TABLE, in declaration order.
ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "broker": {
        "has_editorial": "INTEGER",
        "has_newsletter": "INTEGER",
        "newsletter_evidence": "TEXT",
        "editorial_last_post": "TEXT",
    },
    "draft": {
        "format": "TEXT CHECK (format IN ('long', 'short'))",
        "passes_uniqueness": "INTEGER",
        "max_similarity": "REAL",
        "most_similar_draft_id": "INTEGER",
        "passes_originality": "INTEGER",
        "embedding": "TEXT",
    },
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker (
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

CREATE TABLE IF NOT EXISTS voice_profile (
    broker_id          INTEGER PRIMARY KEY REFERENCES broker(id),
    register           TEXT,
    avg_sentence_len   REAL,
    typical_word_count INTEGER,
    structure_pattern  TEXT,
    vocabulary_markers TEXT,
    themes             TEXT,
    audience_signal    TEXT,
    sample_quotes      TEXT,
    analyzed_at        TEXT
);

CREATE TABLE IF NOT EXISTS angle (
    id               INTEGER PRIMARY KEY,
    broker_id        INTEGER NOT NULL REFERENCES broker(id),
    title            TEXT NOT NULL,
    premise          TEXT,
    audience_value   TEXT,
    sunreef_relevance TEXT,
    score            REAL,
    rejected_reason  TEXT
);

CREATE TABLE IF NOT EXISTS draft (
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

CREATE TABLE IF NOT EXISTS outcome (
    draft_id          INTEGER PRIMARY KEY REFERENCES draft(id),
    sent_at           TEXT,
    response          TEXT,
    published_url     TEXT,
    utm_campaign      TEXT,
    referral_sessions INTEGER,
    inquiries         INTEGER
);

CREATE TABLE IF NOT EXISTS draft_asset (
    id                INTEGER PRIMARY KEY,
    draft_id          INTEGER NOT NULL REFERENCES draft(id),
    asset_type        TEXT,
    asset_url         TEXT,
    metadata          TEXT,
    created_at        TEXT
);
"""


def connect(path: str = "bce.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class SchemaTooNewError(RuntimeError):
    """The file on disk was written by a newer version of this code."""


def _apply_additive_columns(conn: sqlite3.Connection) -> list[str]:
    """ALTER TABLE ... ADD COLUMN for anything the file is missing.

    `CREATE TABLE IF NOT EXISTS` is a no-op on an existing table, so a database
    created before a column was added keeps the old shape and every read of the
    new column raises `OperationalError: no such column`. This closes that gap.
    """
    added: list[str] = []
    for table, columns in ADDITIVE_COLUMNS.items():
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not present:  # table absent entirely; _SCHEMA just created it
            continue
        for column, decl in columns.items():
            if column not in present:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
                added.append(f"{table}.{column}")
    return added


def init_schema(conn: sqlite3.Connection) -> list[str]:
    """Create or upgrade the schema in place. Returns the columns it added."""
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found > SCHEMA_VERSION:
        raise SchemaTooNewError(
            f"database schema version {found} is newer than this code supports "
            f"(version {SCHEMA_VERSION}). Use a matching version of bce, or "
            f"recreate the database with `bce init` against a new --db path."
        )
    conn.executescript(_SCHEMA)
    added = _apply_additive_columns(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")
    conn.commit()
    return added
