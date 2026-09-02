"""Keyword targeting (spec §5b, §8): thresholds, the Semrush bank importer,
and per-draft selection.

Per the task brief, this file builds its own keyword fixtures inline rather
than relying on `bce.seed.seed_example` -- `seed.py` is being edited by
another agent concurrently and must not be touched, and seeding keywords onto
example drafts is a separate follow-up step for someone else.
"""
import sqlite3

from bce import db, keywords

DATA_CSV = "data/keyword_bank.sample.csv"


def _conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


def _insert_keyword(
    conn, phrase, volume, difficulty, *, database="us", competitor_brand=0,
    intent=1, measured_at="2026-09-01", source="semrush", qualifies_override=None,
    segment_relevant=1, editorial=1,
):
    """A directly-inserted keyword row, defaulting to fully selectable
    (segment_relevant=1, editorial=1) -- this file's own tests are about
    selection mechanics (ranking, subset, determinism), not the segment-
    relevance or editorial-intent gates (see test_keywords_segment.py /
    test_keywords_editorial.py for those), so the fixture must not
    accidentally fail every selection through the schema's own conservative
    defaults (segment_relevant defaults to 1, but `editorial` defaults to 0).
    """
    q = (
        keywords.qualifies(volume, difficulty)
        if qualifies_override is None
        else qualifies_override
    )
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, intent, database, "
        "measured_at, qualifies, source, competitor_brand, segment_relevant, "
        "editorial) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (phrase, volume, difficulty, intent, database, measured_at,
         1 if q else 0, source, competitor_brand, segment_relevant, editorial),
    )
    conn.commit()


ANGLE = {
    "title": "What a Catamaran For Sale Actually Costs Bluewater Ready",
    "premise": "Buyers price a catamaran for sale against the sticker, not the refit list.",
    "audience_value": "Helps first-time buyers budget with eyes open.",
    "sunreef_relevance": "Names a Sunreef owner's-version layout in passing.",
}


# --- thresholds --------------------------------------------------------------


def test_threshold_constants_match_spec_section_5b():
    assert keywords.MAX_DIFFICULTY == 30
    assert keywords.MIN_VOLUME == 100


def test_qualifies_is_exclusive_on_difficulty_upper_bound():
    """difficulty < 30, so exactly 30 must fail."""
    assert keywords.qualifies(volume=1000, difficulty=29) is True
    assert keywords.qualifies(volume=1000, difficulty=30) is False


def test_qualifies_is_exclusive_on_volume_lower_bound():
    """volume > 100, so exactly 100 must fail."""
    assert keywords.qualifies(volume=101, difficulty=10) is True
    assert keywords.qualifies(volume=100, difficulty=10) is False


def test_qualifies_matches_the_spec_worked_examples():
    """Spec §5b's own worked examples: some obvious head terms fail on
    difficulty, and the niche's own semantic-expansion terms pass.
    """
    # Fails: difficulty too high.
    assert keywords.qualifies(volume=3600, difficulty=41) is False   # sailing catamaran
    assert keywords.qualifies(volume=8100, difficulty=60) is False   # luxury yacht charter
    assert keywords.qualifies(volume=5400, difficulty=78) is False   # yacht broker
    # Passes: comfortably clears both thresholds.
    assert keywords.qualifies(volume=8100, difficulty=25) is True    # catamaran for sale
    assert keywords.qualifies(volume=4400, difficulty=24) is True    # catamarans for sale
    assert keywords.qualifies(volume=2400, difficulty=6) is True     # yacht vs sailboat


def test_qualifies_handles_none_gracefully():
    assert keywords.qualifies(volume=None, difficulty=10) is False
    assert keywords.qualifies(volume=1000, difficulty=None) is False


# --- load_bank: shape --------------------------------------------------------
#
# `load_bank` ingests a real Semrush export, which is assumed messy: headers
# vary by Semrush tool, delimiter is comma or semicolon, Excel adds a BOM,
# numbers carry thousands separators / decimals / blank / n/a / '-', and a
# row that cannot be parsed must be skipped and reported, never guessed. Every
# scenario below is exercised against a real fixture file under
# tests/fixtures/keyword_exports/, not a synthetic in-memory string, per the
# brief ("Add tests for each of these with real fixture files").

FIXTURES = "tests/fixtures/keyword_exports"


def test_load_bank_reads_the_committed_csv_and_skips_comment_lines():
    conn = _conn()
    result = keywords.load_bank(conn, DATA_CSV)
    assert result.imported == 62  # data/keyword_bank.csv's data-row count
    rows = conn.execute("SELECT * FROM keyword").fetchall()
    assert len(rows) == result.imported
    # Comment lines (starting with '#') must not become bogus rows.
    assert all(not (r["phrase"] or "").startswith("#") for r in rows)


def test_load_bank_sets_database_measured_at_and_source():
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    row = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()
    assert row is not None
    assert row["database"] == "us"
    assert row["measured_at"] == "2026-09-01"
    assert row["source"] == "semrush"
    assert row["volume"] == 8100
    assert row["difficulty"] == 25


def test_load_bank_sets_qualifies_via_the_shared_predicate():
    """Every row in the committed CSV already clears the thresholds (its own
    header comment says so) -- so every qualifying row's `qualifies` must be
    1, computed by the same `keywords.qualifies` this test also calls
    directly.
    """
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    rows = conn.execute("SELECT * FROM keyword").fetchall()
    for row in rows:
        expected = keywords.qualifies(row["volume"], row["difficulty"])
        assert bool(row["qualifies"]) == expected, row["phrase"]


def test_load_bank_result_reports_the_qualify_split():
    """The committed bank's header comment says every row clears both
    thresholds, so the whole file must land in `qualifying`, none in
    `non_qualifying` -- the split this result exists to report.
    """
    conn = _conn()
    result = keywords.load_bank(conn, DATA_CSV)
    assert result.qualifying == 62
    assert result.non_qualifying == 0
    assert result.missed_difficulty == 0
    assert result.missed_volume == 0
    assert result.skipped == ()


def test_load_bank_marks_competitor_brand_rows():
    """The committed CSV still carries an explicit `competitor_brand` column
    -- honoured alongside (not instead of) brand-token detection.
    """
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    lagoon = conn.execute(
        "SELECT * FROM keyword WHERE phrase='lagoon catamaran'"
    ).fetchone()
    assert lagoon["competitor_brand"] == 1
    catamaran_for_sale = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()
    assert catamaran_for_sale["competitor_brand"] == 0


# --- load_bank: idempotency ---------------------------------------------------


def test_load_bank_is_idempotent_no_duplicate_rows():
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    first_count = conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"]

    keywords.load_bank(conn, DATA_CSV)
    second_count = conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"]

    assert first_count == second_count
    assert first_count > 0


def test_load_bank_is_idempotent_metrics_not_multiplied():
    """Running twice must not double or otherwise mutate a stored metric --
    volume for a fixed phrase+database must read identically after either run.
    """
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    before = conn.execute(
        "SELECT volume, difficulty FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()

    keywords.load_bank(conn, DATA_CSV)
    after = conn.execute(
        "SELECT volume, difficulty FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()

    assert before["volume"] == after["volume"] == 8100
    assert before["difficulty"] == after["difficulty"] == 25


def test_load_bank_across_two_overlapping_csvs_stays_idempotent():
    """'The operator will re-export as their research evolves' -- importing
    a second CSV that overlaps the first on phrase+database must update the
    overlapping row in place (not duplicate it) while still adding the truly
    new one.
    """
    conn = _conn()
    keywords.load_bank(conn, DATA_CSV)
    before_total = conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"]

    result = keywords.load_bank(conn, f"{FIXTURES}/overlap_update.csv")
    assert result.imported == 2

    after_total = conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"]
    # Exactly one new phrase ("brand new phrase not in bank") was added;
    # "catamaran for sale" already existed and must have been updated in place.
    assert after_total == before_total + 1

    updated = conn.execute(
        "SELECT volume, difficulty FROM keyword WHERE phrase='catamaran for sale'"
    ).fetchone()
    assert updated["volume"] == 9000
    assert updated["difficulty"] == 20

    # Re-importing the same overlap file again changes nothing further.
    keywords.load_bank(conn, f"{FIXTURES}/overlap_update.csv")
    final_total = conn.execute("SELECT COUNT(*) AS c FROM keyword").fetchone()["c"]
    assert final_total == after_total


# --- load_bank: header aliasing across Semrush tools --------------------------


def test_load_bank_accepts_keyword_magic_tool_headers():
    """Keyword Magic Tool exports 'Keyword' / 'Volume' / 'Keyword Difficulty'
    -- none of which are our own column names -- comma-delimited.
    """
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/keyword_magic_tool.csv")
    assert result.imported == 2
    row = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran interior design'"
    ).fetchone()
    assert row is not None
    assert row["volume"] == 320
    assert row["difficulty"] == 19


def test_load_bank_accepts_position_tracking_headers_and_semicolon_delimiter():
    """Position Tracking exports 'Search Volume' / 'KD', semicolon-delimited."""
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/position_tracking.csv")
    assert result.imported == 2
    row = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran vs monohull'"
    ).fetchone()
    assert row is not None
    assert row["volume"] == 480
    assert row["difficulty"] == 3
    assert bool(row["qualifies"]) is True


def test_load_bank_ignores_unrecognized_extra_columns():
    """Our own committed CSV has a 'theme' column that is not part of the
    keyword table at all -- an unrecognized column must be ignored, not fatal.
    """
    conn = _conn()
    result = keywords.load_bank(conn, DATA_CSV)
    assert result.imported == 62  # theme did not break parsing of a single row


# --- load_bank: BOM + semicolon + thousands separators together ---------------


def test_load_bank_handles_bom_semicolon_and_thousands_separators_together():
    """The combined worst case named directly in the brief: a BOM-prefixed,
    semicolon-delimited file with comma thousands separators in volume.
    """
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/bom_semicolon_thousands.csv")

    excess = conn.execute(
        "SELECT * FROM keyword WHERE phrase='excess catamaran'"
    ).fetchone()
    assert excess is not None, "the BOM on the header must not break header matching"
    assert excess["volume"] == 1900  # thousands separator stripped
    assert excess["difficulty"] == 18.5  # decimal difficulty preserved


def test_load_bank_treats_missing_tokens_as_null_not_a_skip():
    """'n/a' and '-' are recognized missing-value tokens (spec: 'blank, n/a,
    or -') -- the row is still imported with that field NULL, not skipped:
    a keyword with genuinely unknown metrics is still worth having on file
    (it simply cannot qualify -- see keywords.qualifies(None, ...)).
    """
    conn = _conn()
    keywords.load_bank(conn, f"{FIXTURES}/bom_semicolon_thousands.csv")

    privilege = conn.execute(
        "SELECT * FROM keyword WHERE phrase='privilege 510'"
    ).fetchone()
    assert privilege is not None
    assert privilege["difficulty"] is None  # 'n/a' -> NULL, not 0 and not skipped
    assert privilege["qualifies"] == 0

    refit_tips = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran refit tips'"
    ).fetchone()
    assert refit_tips is not None
    assert refit_tips["difficulty"] is None  # '-' -> NULL


def test_load_bank_skips_and_reports_a_row_missing_its_phrase():
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/bom_semicolon_thousands.csv")
    assert len(result.skipped) == 1
    assert "phrase" in result.skipped[0].lower()
    # The five other rows (one skipped) all made it in.
    assert result.imported == 5


def test_load_bank_skips_and_reports_rows_with_unparseable_numbers():
    """A garbage value ('abc', 'twenty') is not a recognized missing token
    (like 'n/a' or '-') and must not be silently guessed at -- the whole row
    is skipped and the reason reported, not the field nulled.
    """
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/malformed_rows.csv")
    assert result.imported == 1
    assert len(result.skipped) == 2
    reasons = " ".join(result.skipped).lower()
    assert "volume" in reasons
    assert "difficulty" in reasons
    survivor = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran survey checklist'"
    ).fetchone()
    assert survivor is not None
    assert survivor["volume"] == 600


# --- load_bank: import everything, judge separately ---------------------------


def test_load_bank_imports_non_qualifying_rows_too():
    """The operator's export reflects their own judgement of what's worth
    considering -- a keyword failing the thresholds is still imported and
    visible, just marked qualifies=0, never discarded.
    """
    conn = _conn()
    keywords.load_bank(conn, f"{FIXTURES}/bom_semicolon_thousands.csv")
    non_qualifying = conn.execute(
        "SELECT * FROM keyword WHERE phrase='privilege 510'"
    ).fetchone()
    assert non_qualifying is not None  # present
    assert non_qualifying["qualifies"] == 0  # but marked as not clearing the bar


def test_load_bank_result_reports_which_threshold_each_failure_missed():
    conn = _conn()
    result = keywords.load_bank(conn, f"{FIXTURES}/bom_semicolon_thousands.csv")
    # 'privilege 510' (difficulty n/a) and 'catamaran refit tips' (difficulty
    # '-') both fail only on difficulty; nothing here fails on volume alone.
    assert result.non_qualifying == 2
    assert result.missed_difficulty == 2
    assert result.missed_volume == 0
    assert result.qualifying == 3  # excess catamaran, excess weight catamaran, lagoon catamaran


def test_load_bank_raises_a_clear_error_when_no_phrase_column_is_found():
    conn = _conn()
    bogus = f"{FIXTURES}/keyword_magic_tool.csv"  # reuse a real file's shape below
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, dir="/tmp"
    ) as f:
        f.write("Domain,Traffic,Rank\nacme.com,1000,5\n")
        path = f.name
    try:
        raised = None
        try:
            keywords.load_bank(conn, path)
        except keywords.NoPhraseColumnError as exc:
            raised = exc
        assert raised is not None
        assert "Domain" in str(raised) or "phrase" in str(raised).lower()
    finally:
        os.unlink(path)


# --- competitor brand detection -----------------------------------------------


def test_detect_competitor_brand_matches_unambiguous_brand_names():
    for phrase in (
        "lagoon catamaran", "leopard catamaran for sale", "aquila 44",
        "fountaine pajot elba", "bali 4.6 catamaran", "nautitech open 40",
        "xquisite yacht", "outremer 55", "catana 53", "hh catamarans 66",
        "gunboat 68",
    ):
        assert keywords.detect_competitor_brand(phrase) is True, phrase


def test_detect_competitor_brand_ignores_unrelated_phrases():
    assert keywords.detect_competitor_brand("catamaran for sale") is False
    assert keywords.detect_competitor_brand("sunreef 60 for sale") is False


def test_detect_competitor_brand_ambiguous_word_requires_boat_context():
    """Spec change brief: 'excess' and 'privilege' are ordinary English
    words. 'excess weight catamaran' must NOT be flagged -- the brand token
    is not adjacent to a boat-context word or a model number, only to
    'weight'. This is the exact false-positive named in the brief.
    """
    assert keywords.detect_competitor_brand("excess weight catamaran") is False
    assert keywords.detect_competitor_brand("special privilege") is False


def test_detect_competitor_brand_ambiguous_word_matches_when_adjacent_to_context():
    assert keywords.detect_competitor_brand("excess catamaran") is True
    assert keywords.detect_competitor_brand("power catamaran excess") is True
    assert keywords.detect_competitor_brand("excess 11") is True  # model number
    assert keywords.detect_competitor_brand("privilege 510") is True  # model number
    assert keywords.detect_competitor_brand("privilege catamaran") is True


def test_load_bank_honours_an_explicit_competitor_brand_column():
    """'Still honour an explicit competitor_brand column if one is present.'
    An explicit 1 gates a phrase our brand list would never catch on its own.
    """
    conn = _conn()
    import csv
    import io
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, dir="/tmp"
    ) as f:
        f.write(
            "phrase,volume,difficulty,competitor_brand\n"
            "some other yacht brand,500,10,1\n"
        )
        path = f.name
    try:
        keywords.load_bank(conn, path)
        row = conn.execute(
            "SELECT * FROM keyword WHERE phrase='some other yacht brand'"
        ).fetchone()
        assert row["competitor_brand"] == 1
    finally:
        os.unlink(path)


# --- select_for_draft: per-format counts --------------------------------------


def _seed_a_healthy_bank(conn):
    """A handful of qualifying, non-competitor keywords relevant to ANGLE, so
    a selection always has enough candidates to fill every format's slots.
    """
    _insert_keyword(conn, "catamaran for sale", 8100, 25)
    _insert_keyword(conn, "catamarans for sale", 4400, 24)
    _insert_keyword(conn, "power catamaran for sale", 2400, 17)
    _insert_keyword(conn, "what is a catamaran", 1900, 25)
    _insert_keyword(conn, "yacht refit", 1900, 10)
    _insert_keyword(conn, "power catamaran", 1600, 28)
    _insert_keyword(conn, "catamaran club", 1000, 20)
    return conn


def test_select_for_draft_long_gets_one_primary_and_up_to_four_secondary():
    conn = _seed_a_healthy_bank(_conn())
    result = keywords.select_for_draft(conn, "long", ANGLE)
    assert result["primary"] is not None
    assert len(result["secondary"]) == 4


def test_select_for_draft_medium_gets_one_primary_and_up_to_two_secondary():
    conn = _seed_a_healthy_bank(_conn())
    result = keywords.select_for_draft(conn, "medium", ANGLE)
    assert result["primary"] is not None
    assert len(result["secondary"]) == 2


def test_select_for_draft_short_gets_one_primary_and_no_secondary():
    conn = _seed_a_healthy_bank(_conn())
    result = keywords.select_for_draft(conn, "short", ANGLE)
    assert result["primary"] is not None
    assert result["secondary"] == []


def test_select_for_draft_caps_secondary_when_bank_is_thin():
    """"up to N" -- a thin bank must not error or pad, just return fewer."""
    conn = _conn()
    _insert_keyword(conn, "catamaran for sale", 8100, 25)
    result = keywords.select_for_draft(conn, "long", ANGLE)
    assert result["primary"] is not None
    assert result["secondary"] == []


# --- select_for_draft: eligibility filters ------------------------------------


def test_select_for_draft_excludes_non_qualifying_keywords():
    conn = _conn()
    # Fails the difficulty threshold (>= 30).
    _insert_keyword(conn, "luxury yacht charter", 8100, 60)
    result = keywords.select_for_draft(conn, "long", ANGLE)
    assert result["primary"] is None
    assert result["secondary"] == []


def test_select_for_draft_excludes_competitor_brand_terms_even_if_qualifying():
    """Spec §5b: competitor brand terms are gated from automatic selection --
    they may pass both thresholds and still must never be picked without an
    explicit human decision, which this task does not build.
    """
    conn = _conn()
    _insert_keyword(conn, "lagoon catamaran", 2400, 26, competitor_brand=1)
    result = keywords.select_for_draft(conn, "long", ANGLE)
    assert result["primary"] is None
    assert result["secondary"] == []


def test_select_for_draft_never_relaxes_thresholds_when_only_gated_keywords_qualify():
    """Even with nothing else in the bank, a qualifying-but-competitor-gated
    keyword must not be substituted in -- the empty result is correct, not a
    bug to work around (spec §5b "When nothing qualifies").
    """
    conn = _conn()
    _insert_keyword(conn, "lagoon catamaran", 2400, 26, competitor_brand=1)
    _insert_keyword(conn, "yacht broker", 5400, 78)  # also fails on difficulty
    for fmt in ("long", "medium", "short"):
        result = keywords.select_for_draft(conn, fmt, ANGLE)
        assert result["primary"] is None
        assert result["secondary"] == []


# --- select_for_draft: nothing qualifies (empty bank) -------------------------


def test_select_for_draft_empty_bank_returns_empty_not_an_error():
    conn = _conn()
    for fmt in ("long", "medium", "short"):
        result = keywords.select_for_draft(conn, fmt, ANGLE)
        assert result == {"primary": None, "secondary": []}


# --- select_for_draft: medium/short are a subset of long ----------------------


def _all_ids(selection: dict) -> set:
    ids = set()
    if selection["primary"] is not None:
        ids.add(selection["primary"]["id"])
    ids |= {row["id"] for row in selection["secondary"]}
    return ids


def test_medium_and_short_keywords_are_a_subset_of_longs():
    """Spec §5b: 'medium and short keywords are a subset of the long draft's'
    -- because they are condensations of the same angle, not independent
    generations. Proven directly against real id sets, not by inspection.
    """
    conn = _seed_a_healthy_bank(_conn())
    long_sel = keywords.select_for_draft(conn, "long", ANGLE)
    medium_sel = keywords.select_for_draft(conn, "medium", ANGLE)
    short_sel = keywords.select_for_draft(conn, "short", ANGLE)

    long_ids = _all_ids(long_sel)
    medium_ids = _all_ids(medium_sel)
    short_ids = _all_ids(short_sel)

    assert medium_ids <= long_ids
    assert short_ids <= long_ids
    # Not a vacuous subset check -- there really is a non-trivial selection.
    assert len(long_ids) >= 5
    assert len(medium_ids) == 3
    assert len(short_ids) == 1


def test_short_primary_equals_long_primary():
    """The single strongest case of the subset rule: the short form's one
    keyword must be the *same* keyword as the long form's primary, not merely
    some other member of the long set.
    """
    conn = _seed_a_healthy_bank(_conn())
    long_sel = keywords.select_for_draft(conn, "long", ANGLE)
    short_sel = keywords.select_for_draft(conn, "short", ANGLE)
    assert short_sel["primary"]["id"] == long_sel["primary"]["id"]


# --- select_for_draft: determinism --------------------------------------------


def test_selection_is_deterministic_across_repeated_calls():
    """Spec §5b: 'same angle + same bank must give the same keywords every
    run, or drafts become unreproducible.'
    """
    conn = _seed_a_healthy_bank(_conn())
    first = keywords.select_for_draft(conn, "long", ANGLE)
    second = keywords.select_for_draft(conn, "long", ANGLE)
    assert _all_ids(first) == _all_ids(second)
    assert first["primary"]["id"] == second["primary"]["id"]
    assert [s["id"] for s in first["secondary"]] == [s["id"] for s in second["secondary"]]


def test_selection_is_deterministic_across_fresh_connections():
    """Not just stable within one Python process/connection -- a fresh
    connection against the same on-disk data must agree too, since drafting
    runs happen as separate CLI invocations.
    """
    conn1 = _seed_a_healthy_bank(_conn())
    first = keywords.select_for_draft(conn1, "long", ANGLE)

    conn2 = db.connect(":memory:")
    db.init_schema(conn2)
    _seed_a_healthy_bank(conn2)
    second = keywords.select_for_draft(conn2, "long", ANGLE)

    assert _all_ids(first) == _all_ids(second)
    assert first["primary"]["phrase"] == second["primary"]["phrase"]


# --- select_for_draft: relevance scoring --------------------------------------


def test_primary_favors_the_keyword_with_more_angle_overlap():
    """A simple, deterministic token-overlap score: the keyword sharing more
    words with the angle's title/premise should outrank one sharing fewer,
    even when the less-relevant one has higher volume.
    """
    conn = _conn()
    # More token overlap with ANGLE's title/premise ("catamaran for sale",
    # "bluewater ready" language) but lower volume.
    _insert_keyword(conn, "catamaran for sale", 1000, 20)
    # Higher volume, but shares nothing with the angle text.
    _insert_keyword(conn, "yacht refit", 50000, 5)
    result = keywords.select_for_draft(conn, "short", ANGLE)
    assert result["primary"]["phrase"] == "catamaran for sale"
