"""Segment relevance (coordinator follow-up to spec §5b): clearing the
volume/difficulty thresholds does not mean a keyword is actually about
Sunreef's segment (60ft+ luxury catamarans). `keyword.segment_relevant` /
`segment_relevant_reason` is a second, independent gate, stored at import
time like `qualifies` -- a recorded judgement, not something recomputed live.

Uses the real operator export `data/semrush-us-2026-09-01.csv` (243 rows,
real Semrush headers) as the primary fixture, per the brief.
"""
from bce import db, keywords

REAL_EXPORT = "data/semrush-us-2026-09-01.csv"


def _conn():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    return conn


# --- classify_segment_relevance: unit-level, the named examples -------------


def test_rug_font_and_pbm_are_excluded_as_not_a_boat():
    """The three examples named directly in the brief: a rug, a typeface, and
    a pharmacy benefit manager, all with excellent KD/volume metrics.
    """
    assert keywords.classify_segment_relevance(
        "catamaran stripe light blue-ivory area rug"
    ) == "not_a_boat"
    assert keywords.classify_segment_relevance("catamaran font") == "not_a_boat"
    assert keywords.classify_segment_relevance("font catamaran") == "not_a_boat"
    assert keywords.classify_segment_relevance("catamaran rx") == "not_a_boat"


def test_street_names_are_excluded_as_not_a_boat():
    assert keywords.classify_segment_relevance("catamaran dr") == "not_a_boat"
    assert keywords.classify_segment_relevance("catamaran drive") == "not_a_boat"


def test_netting_and_net_are_never_excluded_as_not_a_boat():
    """The explicit over-exclusion trap named in the brief: a naive `\\bnet\\b`
    rule would wrongly gate real boat components (trampoline / safety
    netting). Neither must be excluded under any reason.
    """
    assert keywords.classify_segment_relevance("catamaran netting") is None
    assert keywords.classify_segment_relevance("catamaran net") is None


def test_small_watercraft_are_excluded_as_wrong_size_class():
    assert keywords.classify_segment_relevance("blow up catamaran") == "wrong_size_class"
    assert keywords.classify_segment_relevance("catamaran paddle board") == "wrong_size_class"
    assert keywords.classify_segment_relevance("2 man catamaran") == "wrong_size_class"
    assert keywords.classify_segment_relevance("beach catamaran") == "wrong_size_class"


def test_tourist_excursions_are_excluded_as_excursion_tourism():
    assert keywords.classify_segment_relevance("catamaran luau") == "excursion_tourism"
    assert keywords.classify_segment_relevance("catamaran snorkeling") == "excursion_tourism"
    assert keywords.classify_segment_relevance(
        "turtle canyon snorkel cruise by catamaran"
    ) == "excursion_tourism"


def test_racing_classes_are_excluded_as_racing():
    assert keywords.classify_segment_relevance("f50 catamaran") == "racing"
    assert keywords.classify_segment_relevance("a class catamaran") == "racing"
    assert keywords.classify_segment_relevance("international a class catamaran") == "racing"


def test_on_segment_phrases_are_not_excluded():
    for phrase in (
        "catamaran for sale", "catamarans for sale", "power catamaran for sale",
        "what is a catamaran", "yacht refit", "catamaran interior",
        "catamaran vs monohull", "50 foot catamaran",
    ):
        assert keywords.classify_segment_relevance(phrase) is None, phrase


def test_reason_is_a_named_string_not_a_bare_boolean():
    """'Store the reason, don't just store a boolean.'"""
    reason = keywords.classify_segment_relevance("catamaran font")
    assert isinstance(reason, str)
    assert reason in keywords.SEGMENT_EXCLUSION_PATTERNS


# --- load_bank: the real export, real rows -----------------------------------


def test_load_bank_marks_the_named_examples_excluded_in_the_real_export():
    conn = _conn()
    keywords.load_bank(conn, REAL_EXPORT)

    rug = conn.execute(
        "SELECT * FROM keyword WHERE phrase LIKE 'catamaran stripe%area rug'"
    ).fetchone()
    assert rug is not None
    assert rug["segment_relevant"] == 0
    assert rug["segment_relevant_reason"] == "not_a_boat"

    font = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran font'"
    ).fetchone()
    assert font is not None
    assert font["segment_relevant"] == 0

    rx = conn.execute("SELECT * FROM keyword WHERE phrase='catamaran rx'").fetchone()
    assert rx is not None
    assert rx["segment_relevant"] == 0
    assert rx["segment_relevant_reason"] == "not_a_boat"


def test_load_bank_does_not_exclude_netting_in_the_real_export():
    conn = _conn()
    keywords.load_bank(conn, REAL_EXPORT)
    netting = conn.execute(
        "SELECT * FROM keyword WHERE phrase='catamaran netting'"
    ).fetchone()
    assert netting is not None
    assert netting["segment_relevant"] == 1
    assert netting["segment_relevant_reason"] is None

    net = conn.execute("SELECT * FROM keyword WHERE phrase='catamaran net'").fetchone()
    assert net is not None
    assert net["segment_relevant"] == 1


def test_load_bank_result_reports_segment_relevance_split():
    conn = _conn()
    result = keywords.load_bank(conn, REAL_EXPORT)
    assert result.segment_relevant + result.segment_excluded == result.imported
    assert result.segment_excluded > 0  # the real export really does have off-target rows
    assert "not_a_boat" in result.excluded_by_reason
    assert result.excluded_by_reason["not_a_boat"] > 0
    # Volume is tracked per reason too, not just a count.
    assert result.excluded_volume_by_reason["not_a_boat"] > 0


def test_load_bank_segment_relevance_counts_are_stable_across_repeated_imports():
    """Same file, same heuristic, same answer every time -- a keyword's
    segment classification must not depend on import order or repetition.
    """
    conn1 = _conn()
    first = keywords.load_bank(conn1, REAL_EXPORT)

    conn2 = _conn()
    second = keywords.load_bank(conn2, REAL_EXPORT)

    assert first.segment_relevant == second.segment_relevant
    assert first.segment_excluded == second.segment_excluded
    assert first.excluded_by_reason == second.excluded_by_reason
    assert first.excluded_volume_by_reason == second.excluded_volume_by_reason

    # Re-importing into the SAME connection a second time must also agree.
    third = keywords.load_bank(conn1, REAL_EXPORT)
    assert third.segment_relevant == first.segment_relevant
    assert third.segment_excluded == first.segment_excluded


def test_load_bank_preserves_a_manual_segment_relevant_correction_on_reimport():
    """'A keyword must be able to be marked relevant despite a pattern
    match' -- once a human flips segment_relevant back to 1 (a correction),
    re-importing the same export must not silently revert it back to the
    heuristic's original verdict. The reason column stays untouched too, so
    the operator can still see why the heuristic originally flagged it.
    """
    conn = _conn()
    keywords.load_bank(conn, REAL_EXPORT)
    conn.execute(
        "UPDATE keyword SET segment_relevant=1 WHERE phrase='catamaran font'"
    )
    conn.commit()

    keywords.load_bank(conn, REAL_EXPORT)

    row = conn.execute(
        "SELECT segment_relevant FROM keyword WHERE phrase='catamaran font'"
    ).fetchone()
    assert row["segment_relevant"] == 1


# --- select_for_draft: the third eligibility filter ---------------------------


def test_select_for_draft_excludes_segment_irrelevant_keywords():
    conn = _conn()
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, "
        "measured_at, qualifies, source, competitor_brand, segment_relevant, "
        "segment_relevant_reason) VALUES "
        "('catamaran font', 170, 20, 'us', '2026-09-01', 1, 'semrush', 0, 0, 'not_a_boat')"
    )
    conn.commit()
    result = keywords.select_for_draft(
        conn, "long",
        {"title": "Catamaran font choices", "premise": "", "audience_value": "", "sunreef_relevance": ""},
    )
    assert result["primary"] is None
    assert result["secondary"] == []


def test_select_for_draft_still_returns_relevant_qualifying_keywords():
    conn = _conn()
    conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, "
        "measured_at, qualifies, source, competitor_brand, segment_relevant, "
        "segment_relevant_reason, editorial) VALUES "
        "('catamaran for sale', 8100, 25, 'us', '2026-09-01', 1, 'semrush', 0, 1, NULL, 1)"
    )
    conn.commit()
    angle = {
        "title": "Catamaran for sale checklist", "premise": "", "audience_value": "",
        "sunreef_relevance": "",
    }
    result = keywords.select_for_draft(conn, "short", angle)
    assert result["primary"] is not None
    assert result["primary"]["phrase"] == "catamaran for sale"


# --- the widened pattern table: both directions ----------------------------

# Keywords that MUST stay eligible. Over-exclusion is the dangerous failure
# here: a wrongly-excluded on-topic term is invisible on review, whereas a rug
# that slips through is obvious the moment anyone reads the list.
MUST_SURVIVE = (
    "catamaran netting",                # trampoline netting: a real component
    "cruising catamaran",               # ownership topic, not a day trip
    "cruising in a catamaran",          # ditto -- "cruising" != "cruise"
    "catamaran charter mediterranean",  # week-long charter is broker business
    "solar catamaran",                  # the Sunreef Eco cluster
    "electric catamaran",
    "hybrid catamaran",
    "luxury catamaran",
    "catamaran insurance",
    "how to finance a catamaran",
    "catamaran hull",
    "trimaran vs catamaran",
)

# Keywords that MUST be excluded, each representing one exclusion reason.
MUST_BE_EXCLUDED = (
    "catamaran stripe light blue-ivory area rug",  # not_a_boat
    "catamaran images pictures",                   # not_a_boat
    "sunset catamaran cruise",                     # excursion_tourism
    "catamaran tours punta cana",                  # excursion_tourism
    "family catamaran vacations",                  # excursion_tourism
    "smallest catamaran",                          # wrong_size_class
    "catamaran small",                             # wrong_size_class
    "2 person catamaran",                          # wrong_size_class
    "racing catamaran",                            # racing
    "catamara",                                    # non_english
    "whats a catamaran",                           # non_english
    "glacier bay catamaran",                       # other_brand
    "catamaran club",                              # other_brand
)


def test_on_topic_keywords_are_not_over_excluded():
    conn = _conn()
    keywords.load_bank(conn, REAL_EXPORT)
    for phrase in MUST_SURVIVE:
        row = conn.execute(
            "SELECT segment_relevant, segment_relevant_reason FROM keyword "
            "WHERE phrase=?", (phrase,)
        ).fetchone()
        assert row is not None, f"{phrase!r} missing from the export fixture"
        assert row["segment_relevant"] == 1, (
            f"{phrase!r} was wrongly excluded as "
            f"{row['segment_relevant_reason']!r}"
        )


def test_off_target_keywords_are_excluded():
    conn = _conn()
    keywords.load_bank(conn, REAL_EXPORT)
    for phrase in MUST_BE_EXCLUDED:
        row = conn.execute(
            "SELECT segment_relevant, segment_relevant_reason FROM keyword "
            "WHERE phrase=?", (phrase,)
        ).fetchone()
        assert row is not None, f"{phrase!r} missing from the export fixture"
        assert row["segment_relevant"] == 0, f"{phrase!r} slipped through"
        assert row["segment_relevant_reason"], (
            f"{phrase!r} excluded without a recorded reason -- the reason is "
            "what lets an operator correct a bad rule"
        )


def test_cruise_and_cruising_are_distinguished():
    """The split that token-exact matching buys us, stated as its own test
    because a substring implementation would silently break it: a "cruise" is
    a booked day trip, "cruising" is what an owner does with the boat.
    """
    assert keywords.classify_segment_relevance("catamaran sunset cruise")
    assert keywords.classify_segment_relevance("cruising catamaran") is None
