"""SQLite store — single source of truth for pipeline state (spec §7, §8)."""
import sqlite3

SCHEMA_TABLES = ("broker", "voice_profile", "angle", "draft", "draft_asset", "outcome")

#: Bumped whenever the shape below changes. Stored in `PRAGMA user_version` so
#: an existing file can be recognised instead of silently keeping an old shape
#: (`CREATE TABLE IF NOT EXISTS` never adds a column to a table that exists).
#: Bumped to 3 for spec v0.6's three-format change: `draft.format`'s CHECK
#: grows from `('long', 'short')` to `('long', 'medium', 'short')`. Unlike
#: every other change so far, this is not an additive `ALTER TABLE ADD
#: COLUMN` -- SQLite has no `ALTER TABLE ... ALTER CHECK`, so a v2 database
#: needs `_rebuild_draft_table_for_medium_format` below (create-copy-drop-
#: rename), not just a new column.
SCHEMA_VERSION = 3

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
        "format": "TEXT CHECK (format IN ('long', 'medium', 'short'))",
        "passes_uniqueness": "INTEGER",
        "max_similarity": "REAL",
        "most_similar_draft_id": "INTEGER",
        "passes_originality": "INTEGER",
        "embedding": "TEXT",
    },
    # Migrates a database created before the table was corrected to match
    # spec §8 (F5): the original shape was
    # `draft_asset(id, draft_id, asset_type, asset_url, metadata, created_at)`,
    # which shares no column with the spec beyond `draft_id`, and silently
    # dropped `usage_rights_confirmed` -- the column §10.7 requires ("Any
    # image or video supplied to a broker must carry explicit permission for
    # that broker to publish it"). `CREATE TABLE IF NOT EXISTS` is a no-op on
    # a table that already exists in the old shape, so the three correct
    # columns are added additively here; the old columns are left in place
    # (harmless -- nothing reads or writes this table yet) rather than
    # dropped, since SQLite has no simple `DROP COLUMN` this migration path
    # can rely on.
    "draft_asset": {
        "asset_id": "TEXT",
        "provider": "TEXT",
        "usage_rights_confirmed": "INTEGER",
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
    format                        TEXT CHECK (format IN ('long', 'medium', 'short')),
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
    draft_id                INTEGER NOT NULL REFERENCES draft(id),
    asset_id                TEXT,
    provider                TEXT,
    usage_rights_confirmed  INTEGER
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


def _draft_format_check_needs_rebuild(conn: sqlite3.Connection) -> bool:
    """True when `draft.format` already exists but its CHECK predates 'medium'.

    If `format` is missing entirely, the additive-column path below adds it
    fresh with the current (three-value) CHECK text, so no rebuild is needed
    there -- this only catches the case `ALTER TABLE ADD COLUMN` cannot fix:
    a CHECK constraint already baked into the table's stored SQL.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
    if "format" not in cols:
        return False
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='draft'"
    ).fetchone()
    sql = row["sql"] if row and row["sql"] else ""
    return "medium" not in sql


def _rebuild_draft_table_for_medium_format(conn: sqlite3.Connection) -> None:
    """Rebuild `draft` in place so its format CHECK allows 'medium' too.

    SQLite has no `ALTER TABLE ... ALTER CHECK` (or DROP/ADD CONSTRAINT); the
    documented workaround is SQLite's own "12-step" procedure: rename the old
    table out of the way, create the new (correct) one, copy every row across,
    then drop the renamed original. `outcome` and `draft_asset` both hold a
    `REFERENCES draft(id)` foreign key, so `foreign_keys` is turned off for the
    duration -- otherwise renaming `draft` away mid-migration trips FK
    enforcement on those other tables even though the rename preserves the
    name (and therefore the reference) by the time the migration finishes.
    """
    old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(draft)")]
    fk_was_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("ALTER TABLE draft RENAME TO _draft_pre_medium_migration")
        # _SCHEMA declares the post-migration `draft` shape (three-value
        # CHECK); every other CREATE TABLE IF NOT EXISTS in it is a no-op
        # since those tables already exist.
        conn.executescript(_SCHEMA)
        new_cols = {r["name"] for r in conn.execute("PRAGMA table_info(draft)")}
        shared = [c for c in old_cols if c in new_cols]
        cols_sql = ", ".join(shared)
        conn.execute(
            f"INSERT INTO draft ({cols_sql}) "
            f"SELECT {cols_sql} FROM _draft_pre_medium_migration"
        )
        conn.execute("DROP TABLE _draft_pre_medium_migration")
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")


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
    if _draft_format_check_needs_rebuild(conn):
        _rebuild_draft_table_for_medium_format(conn)
    added = _apply_additive_columns(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION:d}")
    conn.commit()
    return added
