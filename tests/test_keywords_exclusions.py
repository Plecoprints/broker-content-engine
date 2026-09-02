"""The operator's curated banks (spec §5b "Approved and excluded banks").

Two guarantees are tested here, and they are different in kind:

  * the approved bank must *import* -- its real column names, not the ones we
    happened to write our own committed fixture with; and
  * the excluded bank must *block*, outranking every heuristic gate and
    surviving a later import that would re-derive those gates as passing.

The second is the one worth having tests for. Every automatic gate in §5b is
derived from metrics, so any of them can be re-derived to `1` by a future
Semrush export; the operator's blocklist is the only gate that records a
human decision, and it has to hold against exactly that.
"""
import csv

import pytest

from bce import db, keywords

APPROVED_CSV = "data/keywords-approved.csv"
EXCLUDED_CSV = "data/keywords-excluded.csv"


def _conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


def _write(tmp_path, name, header, rows):
    path = tmp_path / name
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)
    return str(path)


# --- the approved bank imports ------------------------------------------


def test_monthly_volume_header_is_recognised(tmp_path):
    """`monthly_volume` is what the operator's export actually calls it.

    Regression: the alias set held only {volume, search volume}, so every row
    parsed with `volume=None`, `qualifies()` returned False for all of them,
    and a 148-keyword bank imported as 148 non-qualifying rows -- a silent
    total failure that still exited 0.
    """
    path = _write(
        tmp_path, "approved.csv",
        ["keyword", "monthly_volume", "difficulty", "intent"],
        [["what is a catamaran", "1900", "25", "informational"]],
    )
    conn = _conn()
    result = keywords.load_bank(conn, path)
    assert result.imported == 1
    assert result.qualifying == 1, "volume column was not read"


def test_real_approved_bank_imports_and_every_row_qualifies():
    conn = _conn()
    result = keywords.load_bank(conn, APPROVED_CSV)
    assert result.imported == 148
    assert result.qualifying == 148
    assert result.non_qualifying == 0
    assert not result.skipped


# --- the excluded bank blocks -------------------------------------------


def test_real_excluded_bank_loads():
    conn = _conn()
    result = keywords.load_exclusions(conn, EXCLUDED_CSV)
    assert result.imported == 95
    assert not result.skipped


def test_the_two_banks_do_not_overlap():
    """A phrase in both files would mean the operator's own banks disagree;
    the blocklist would win, silently dropping an approved keyword."""
    approved = {
        keywords.normalize_phrase(r["keyword"])
        for r in csv.DictReader(open(APPROVED_CSV)) if r.get("keyword")
    }
    excluded = {
        keywords.normalize_phrase(r["keyword"])
        for r in csv.DictReader(open(EXCLUDED_CSV)) if r.get("keyword")
    }
    assert approved & excluded == set()


def test_excluded_phrase_is_never_selected_though_all_gates_pass():
    """`catamaran club` is excluded by hand (other_brand) yet scores 1000
    volume at KD 20 -- it clears every automatic gate. The blocklist is the
    only thing standing between it and a draft."""
    conn = _conn()
    keywords.load_bank(conn, APPROVED_CSV)
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies,"
        " segment_relevant, editorial, competitor_brand)"
        " VALUES ('catamaran club', 1000, 20, 'us', 1, 1, 1, 0)"
    )
    conn.commit()
    keywords.load_exclusions(conn, EXCLUDED_CSV)

    angle = {"title": "Inside the catamaran club scene", "premise": "clubs",
             "audience_value": "", "sunreef_relevance": ""}
    picked = keywords.select_for_draft(conn, "long", angle)
    chosen = [picked["primary"]] + list(picked["secondary"])
    phrases = {keywords.normalize_phrase(k["phrase"]) for k in chosen}
    assert "catamaran club" not in phrases


def test_blocklist_matching_ignores_case_and_spacing():
    conn = _conn()
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, qualifies,"
        " segment_relevant, editorial, competitor_brand)"
        " VALUES ('  Racing   CATAMARAN ', 900, 10, 'us', 1, 1, 1, 0)"
    )
    conn.commit()
    keywords.load_exclusions(conn, EXCLUDED_CSV)
    picked = keywords.select_for_draft(conn, "long", None)
    assert picked["primary"] is None, "spacing/case variant slipped past the blocklist"


def test_reimporting_a_bank_cannot_resurrect_a_blocked_phrase(tmp_path):
    """The scenario the blocklist exists for: a later export reintroduces an
    excluded phrase with metrics that pass, re-deriving every heuristic gate."""
    conn = _conn()
    keywords.load_exclusions(conn, EXCLUDED_CSV)
    later_export = _write(
        tmp_path, "later.csv",
        ["keyword", "monthly_volume", "difficulty", "intent"],
        [["catamaran club", "1000", "20", "informational"]],
    )
    result = keywords.load_bank(conn, later_export)
    assert result.qualifying == 1, "precondition: the row does clear the thresholds"
    picked = keywords.select_for_draft(conn, "long", None)
    assert picked["primary"] is None


def test_loading_exclusions_is_idempotent():
    conn = _conn()
    keywords.load_exclusions(conn, EXCLUDED_CSV)
    keywords.load_exclusions(conn, EXCLUDED_CSV)
    n = conn.execute("SELECT COUNT(*) FROM excluded_keyword").fetchone()[0]
    assert n == 95


def test_exclusion_reason_is_preserved():
    conn = _conn()
    keywords.load_exclusions(conn, EXCLUDED_CSV)
    row = conn.execute(
        "SELECT reason FROM excluded_keyword WHERE phrase='catamaran club'"
    ).fetchone()
    assert row["reason"] == "off segment: other_brand"


def test_missing_exclusion_file_is_reported_not_swallowed():
    conn = _conn()
    with pytest.raises(FileNotFoundError):
        keywords.load_exclusions(conn, "data/does-not-exist.csv")


def test_exclusion_file_without_a_keyword_column_is_refused(tmp_path):
    path = _write(tmp_path, "bad.csv", ["notes", "count"], [["x", "1"]])
    conn = _conn()
    with pytest.raises(keywords.NoPhraseColumnError):
        keywords.load_exclusions(conn, path)
