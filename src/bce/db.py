"""SQLite store — single source of truth for pipeline state (spec §7, §8)."""
import sqlite3

SCHEMA_TABLES = (
    "broker", "voice_profile", "angle", "draft", "draft_asset", "outcome",
    "keyword", "draft_keyword", "source_fingerprint", "excluded_keyword",
)

#: Bumped whenever the shape below changes. Stored in `PRAGMA user_version` so
#: an existing file can be recognised instead of silently keeping an old shape
#: (`CREATE TABLE IF NOT EXISTS` never adds a column to a table that exists).
#: Bumped to 3 for spec v0.6's three-format change: `draft.format`'s CHECK
#: grows from `('long', 'short')` to `('long', 'medium', 'short')`. Unlike
#: every other change so far, this is not an additive `ALTER TABLE ADD
#: COLUMN` -- SQLite has no `ALTER TABLE ... ALTER CHECK`, so a v2 database
#: needs `_rebuild_draft_table_for_medium_format` below (create-copy-drop-
#: rename), not just a new column.
#: Bumped to 4 for spec §5b/§8's keyword targeting: two brand-new tables,
#: `keyword` and `draft_keyword`. Unlike the format-CHECK rebuild, this needs
#: no rewrite of anything that already exists -- `CREATE TABLE IF NOT EXISTS`
#: in `_SCHEMA` below is sufficient for an old-shaped database to gain them,
#: since neither table previously existed in any shape to migrate away from.
#: Bumped to 5 for spec §10.3's three originality gates. `draft` gains
#: `passes_tailored` / `tailored_score` (Gate 2 -- "Tailored" -- had no
#: column at all: `passes_uniqueness`/`max_similarity`/`most_similar_draft_id`
#: /`embedding` belong to Gate 1 "Unique", and `passes_originality` was
#: already named for Gate 3 "Original") and `originality_overlap` (Gate 3's
#: collision figure, the containment-based counterpart to Gate 1's
#: `max_similarity`). A brand-new table, `source_fingerprint`, backs Gate 3
#: -- see `bce.fingerprint`'s module docstring for why it stores shingle
#: hashes and not text. Purely additive (new columns via `ALTER TABLE ADD
#: COLUMN`, a new table via `CREATE TABLE IF NOT EXISTS`), so no rebuild is
#: needed this time, unlike version 3's format-CHECK migration.
#: Bumped to 6 for the operator's curated keyword banks (spec §5b "Approved and
#: excluded banks"): one new table, `excluded_keyword`, holding the phrases the
#: operator has ruled out by hand. Additive -- `CREATE TABLE IF NOT EXISTS`
#: only, nothing existing is rewritten.
#: Bumped to 7 for §10.9's fourth gate: `draft.passes_no_product_claims` and
#: `draft.product_claims_found`. Additive `ALTER TABLE ADD COLUMN` only.
SCHEMA_VERSION = 7

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
        # Spec §10.4 (as revised 2026-09-02) / §10.9's fourth gate: no
        # specific claim about a named Sunreef vessel. `product_claims_found`
        # holds what tripped it -- a gate reporting only "failed" cannot be
        # acted on, and both a reviewer and a redraft prompt need the
        # offending text. See `bce.claims`.
        "passes_no_product_claims": "INTEGER",
        "product_claims_found": "TEXT",
        # Spec §10.3 Gate 2 ("Tailored"): register/structure match against
        # this broker's own voice_profile, scored in `bce.originality.
        # score_tailored`. Recorded for every format (spec v0.6 §5: "compute
        # and record the score"), but only *enforced* -- see
        # `bce.originality.TAILORED_BLOCKING_FORMATS` -- for medium/short;
        # long is never blocked on it.
        "passes_tailored": "INTEGER",
        "tailored_score": "REAL",
        # Spec §10.3 Gate 3 ("Original"): the containment figure `bce.
        # originality.check_original` computed against this broker's
        # `source_fingerprint` rows -- the counterpart to Gate 1's
        # `max_similarity`, so a human sees *how much* overlap was found,
        # not just pass/fail.
        "originality_overlap": "REAL",
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
    embedding                     TEXT,
    passes_no_product_claims      INTEGER,
    product_claims_found          TEXT
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

-- spec §5b/§8: keyword targeting. `phrase` + `database` are unique together
-- (the same phrase carries different metrics in different regional Semrush
-- databases, so phrase alone is not the identity -- spec §8). `qualifies` is
-- stored at import time, not a view or generated column -- see
-- `bce.keywords.qualifies`, the one place the §5b threshold rule lives; this
-- column only ever records what that predicate returned *when measured*, and
-- nothing here recomputes it on read.
--
-- `competitor_brand` is not in the spec §8 column list verbatim, but §5b's
-- "Competitor brand terms" section requires it as "a real column" so
-- selection can filter it out without a human decision -- there is nowhere
-- else in the row to derive it from.
-- `segment_relevant` / `segment_relevant_reason`: a second, independent gate
-- from `qualifies` -- clearing the §5b volume/difficulty thresholds does not
-- mean a phrase is actually about Sunreef's segment (60ft+ luxury
-- catamarans). "catamaran stripe light blue-ivory area rug" clears both
-- thresholds easily and is a rug. Stored at import time for the same reason
-- `qualifies` is: it is a judgement recorded at a point in time, not
-- recomputed at read. Defaults to 1 (relevant) so a row inserted directly
-- (tests, a manual correction) without going through the heuristic is not
-- silently excluded. See `bce.keywords.classify_segment_relevance`.
--
-- `intent_labels` / `editorial`: spec §5b "Editorial intent only" -- a third
-- gate. The engine writes editorial content, not commercial landing-page
-- copy, so a keyword is only automatically selectable when Semrush's Intent
-- field includes Informational and excludes both Transactional and
-- Navigational (Commercial is retained -- comparison content is genuinely
-- editorial). `intent_labels` stores the parsed intent set so `editorial`'s
-- reasoning stays inspectable, not just a bare flag. Defaults to 0
-- (non-editorial) -- an absent/blank Intent cell is unknown, not assumed
-- informational (see `bce.keywords.is_editorial_intent`).
CREATE TABLE IF NOT EXISTS keyword (
    id                        INTEGER PRIMARY KEY,
    phrase                    TEXT NOT NULL,
    volume                    INTEGER,
    difficulty                INTEGER,
    intent                    INTEGER,
    database                  TEXT NOT NULL DEFAULT 'us',
    measured_at               TEXT,
    qualifies                 INTEGER NOT NULL,
    source                    TEXT,
    competitor_brand          INTEGER NOT NULL DEFAULT 0,
    segment_relevant          INTEGER NOT NULL DEFAULT 1,
    segment_relevant_reason   TEXT,
    intent_labels             TEXT,
    editorial                 INTEGER NOT NULL DEFAULT 0,
    UNIQUE (phrase, database)
);

CREATE TABLE IF NOT EXISTS draft_keyword (
    draft_id   INTEGER NOT NULL REFERENCES draft(id),
    keyword_id INTEGER NOT NULL REFERENCES keyword(id),
    role       TEXT NOT NULL CHECK (role IN ('primary', 'secondary'))
);

-- spec §5b: the operator's hand-curated exclusion bank. A *blocklist*, held
-- separately from `keyword` on purpose: `keyword.segment_relevant` records
-- what a heuristic decided at import time and is re-derived by every future
-- import, while this table records what a human decided and must survive
-- those imports. A phrase here is never selectable, whatever metrics a later
-- Semrush export gives it. `phrase` is stored casefolded and
-- whitespace-collapsed so matching does not depend on export formatting.
CREATE TABLE IF NOT EXISTS excluded_keyword (
    phrase    TEXT NOT NULL,
    database  TEXT NOT NULL DEFAULT 'us',
    reason    TEXT,
    UNIQUE (phrase, database)
);

-- spec §8: "Exactly one primary per draft" -- enforced here by a partial
-- unique index, not application code, so it holds even against a caller that
-- forgets to check.
CREATE UNIQUE INDEX IF NOT EXISTS idx_draft_keyword_one_primary
    ON draft_keyword (draft_id) WHERE role = 'primary';

-- spec §10.3 Gate 3 ("Original"): shingle-hash fingerprints of a broker's
-- own published prose, populated during profiling
-- (`bce.profile.profile_broker`) from the article text `bce.articles.
-- collect_broker_articles` fetches -- the same text that is discarded
-- everywhere else, per spec §10.3's "never full article text". Deliberately
-- has NO text/prose column of any kind: `shingle_hash` is a one-way hash
-- (`bce.fingerprint.shingle_hashes`), so this table cannot be used to
-- reconstruct what a broker actually wrote, only to measure overlap against
-- it. `(broker_id, shingle_hash)` as the primary key makes the table a set
-- per broker -- the same shingle recurring across articles, or a re-profile
-- re-deriving the same hash, is a no-op, not a duplicate row.
CREATE TABLE IF NOT EXISTS source_fingerprint (
    broker_id     INTEGER NOT NULL REFERENCES broker(id),
    shingle_hash  INTEGER NOT NULL,
    PRIMARY KEY (broker_id, shingle_hash)
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
