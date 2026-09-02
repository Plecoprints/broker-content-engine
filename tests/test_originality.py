"""The three originality gates (spec §10.3): Unique, Tailored, Original.

Each gate is tested in isolation, then `run_gates` is tested as the
combining orchestrator, including the one asymmetry the spec requires:
Gate 2 (Tailored) is blocking for medium/short but never for long (spec
v0.6 §5).
"""
import json

from bce import db, originality


class FakeEmbeddingClient:
    """Returns a caller-controlled vector regardless of input, so tests can
    force a specific cosine similarity between two calls without a real
    Voyage call. `None` simulates the "embedding failed" degrade-to-None
    contract every client in this codebase shares.
    """

    def __init__(self, vector=(1.0, 0.0, 0.0)):
        self.vector = vector
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if self.vector is None:
            return None
        return list(self.vector)


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def _broker(conn, domain="fp.invalid"):
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('T', ?, 'manual')",
        (domain,),
    )
    return conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]


def _insert_draft(conn, *, format="long", embedding=None, angle_id=None) -> int:
    if angle_id is None:
        bid = _broker(conn, domain=f"b{conn.execute('SELECT COUNT(*) c FROM broker').fetchone()['c']}.invalid")
        angle_id = conn.execute(
            "INSERT INTO angle (broker_id, title) VALUES (?, 'A')", (bid,)
        ).lastrowid
    cursor = conn.execute(
        "INSERT INTO draft (angle_id, body_md, format, embedding, status) "
        "VALUES (?, 'x', ?, ?, 'pending_review')",
        (angle_id, format, json.dumps(embedding) if embedding is not None else None),
    )
    conn.commit()
    return cursor.lastrowid


# --- Gate 1: Unique (corpus-wide, scoped within format) --------------------


def test_uniqueness_threshold_is_088():
    assert originality.UNIQUENESS_THRESHOLD == 0.88


def test_first_draft_of_a_format_has_nothing_to_compare_and_passes():
    conn = _conn()
    result = originality.check_uniqueness(
        conn, "long", "brand new body", FakeEmbeddingClient(vector=(1, 0, 0))
    )
    assert result["passes"] is True
    assert result["max_similarity"] is None
    assert result["most_similar_draft_id"] is None
    assert result["embedding"] == [1.0, 0.0, 0.0]


def test_near_identical_vector_in_same_format_fails_uniqueness():
    conn = _conn()
    existing_id = _insert_draft(conn, format="long", embedding=[1.0, 0.0, 0.0])

    result = originality.check_uniqueness(
        conn, "long", "a near duplicate", FakeEmbeddingClient(vector=(1.0, 0.0, 0.0))
    )

    assert result["passes"] is False
    assert result["max_similarity"] == 1.0
    assert result["most_similar_draft_id"] == existing_id


def test_dissimilar_vector_passes_uniqueness():
    conn = _conn()
    _insert_draft(conn, format="long", embedding=[1.0, 0.0, 0.0])

    result = originality.check_uniqueness(
        conn, "long", "something else entirely", FakeEmbeddingClient(vector=(0.0, 1.0, 0.0))
    )

    assert result["passes"] is True
    assert result["max_similarity"] == 0.0


def test_comparison_is_scoped_within_format_long_never_compared_to_short():
    """Spec v0.6 §5: long and short versions of one article are near-
    identical by design, so cross-format comparison must never happen --
    otherwise every article would flag as a duplicate of its own summary.
    """
    conn = _conn()
    _insert_draft(conn, format="short", embedding=[1.0, 0.0, 0.0])

    result = originality.check_uniqueness(
        conn, "long", "a pillar article", FakeEmbeddingClient(vector=(1.0, 0.0, 0.0))
    )

    assert result["passes"] is True
    assert result["max_similarity"] is None


def test_embedding_failure_does_not_pass_an_unverifiable_draft():
    """The gate cannot claim uniqueness it never checked -- an embedding
    call that fails (no key, network error, refusal -- all degrade to None
    per `EmbeddingClient.embed`) must not silently pass.
    """
    conn = _conn()
    result = originality.check_uniqueness(
        conn, "long", "body", FakeEmbeddingClient(vector=None)
    )
    assert result["passes"] is False
    assert result["embedding"] is None


def test_uniqueness_boundary_is_exclusive_of_the_threshold():
    """spec: 'threshold 0.88' as the point at which a draft fails -- a
    similarity of exactly 0.88 must fail, not narrowly pass.
    """
    conn = _conn()
    _insert_draft(conn, format="long", embedding=[1.0, 0.0])
    # cos angle chosen so similarity comes out to exactly 0.88.
    import math
    theta = math.acos(0.88)
    vector = (math.cos(theta), math.sin(theta))
    result = originality.check_uniqueness(
        conn, "long", "body", FakeEmbeddingClient(vector=vector)
    )
    assert abs(result["max_similarity"] - 0.88) < 1e-9
    assert result["passes"] is False


# --- Gate 2: Tailored (voice match, no API call) ----------------------------


PROFILE = {
    "register": "warm professional",
    "avg_sentence_len": 18.0,
    "typical_word_count": 600,
    "structure_pattern": {"paragraphs_per_article": 6, "words_per_paragraph": 100},
    "vocabulary_markers": [],
    "themes": [],
    "audience_signal": "owners",
    "sample_quotes": [],
}


def test_tailored_score_is_between_zero_and_one():
    body = "Word " * 600
    score = originality.score_tailored(PROFILE, body)
    assert 0.0 <= score <= 1.0


def test_tailored_score_is_high_for_a_close_word_count_match():
    body = ("Short sentence here. " * 100).strip()  # ~300 words
    profile = {**PROFILE, "typical_word_count": 300, "avg_sentence_len": 3.0,
               "structure_pattern": {}}
    score = originality.score_tailored(profile, body)
    assert score > 0.5


def test_tailored_score_is_low_for_a_wildly_off_word_count():
    body = "word " * 50  # 50 words
    profile = {**PROFILE, "typical_word_count": 5000, "avg_sentence_len": 5.0,
               "structure_pattern": {}}
    score = originality.score_tailored(profile, body)
    assert score < 0.3


def test_tailored_score_is_none_when_the_profile_has_nothing_to_compare():
    """A profile with a register but no statistics is a legitimate state --
    `drafting.draft_for_broker` refuses to draft only when `register` is NULL,
    not when the statistics half is missing.

    So "not comparable" must be distinguishable from "scored zero". Returning
    0.0 here would be indistinguishable from a genuinely terrible voice match
    and, because the tailored gate blocks medium and short, would reject every
    one of those drafts for a thinly-profiled broker.
    """
    assert originality.score_tailored({}, "Some draft text here.") is None


def test_tailored_score_of_empty_body_is_zero_not_none():
    """The other direction, and the reason None and 0.0 must stay distinct:
    an empty draft really does match nothing. That is a measured zero, not an
    absence of anything to measure against.
    """
    assert originality.score_tailored(PROFILE, "") == 0.0


def test_tailored_blocking_formats_are_medium_and_short_only():
    assert originality.TAILORED_BLOCKING_FORMATS == {"medium", "short"}


# --- Gate 3: Original (vs. broker's own published prose) -------------------


def test_original_passes_when_broker_has_no_fingerprints_yet():
    conn = _conn()
    bid = _broker(conn)
    result = originality.check_original(conn, bid, "a fresh draft body with several words")
    assert result["passes"] is True
    assert result["containment"] is None


def test_original_fails_on_heavy_shingle_overlap_with_source():
    conn = _conn()
    bid = _broker(conn)
    from bce.fingerprint import shingle_hashes

    source_text = (
        "Sunreef catamarans deliver exceptional bluewater comfort for owners "
        "who value volume, stability, and genuine ocean-crossing capability"
    )
    for h in shingle_hashes(source_text):
        conn.execute(
            "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) "
            "VALUES (?, ?)", (bid, h),
        )
    conn.commit()

    # A "draft" that is the same text almost verbatim.
    result = originality.check_original(conn, bid, source_text)
    assert result["passes"] is False
    assert result["containment"] == 1.0


def test_original_passes_on_genuinely_different_prose():
    conn = _conn()
    bid = _broker(conn)
    from bce.fingerprint import shingle_hashes

    source_text = (
        "Sunreef catamarans deliver exceptional bluewater comfort for owners "
        "who value volume, stability, and genuine ocean-crossing capability"
    )
    for h in shingle_hashes(source_text):
        conn.execute(
            "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) "
            "VALUES (?, ?)", (bid, h),
        )
    conn.commit()

    different = (
        "Provisioning for a two-week Mediterranean crossing means packing "
        "less than the checklists suggest and testing the watermaker early"
    )
    result = originality.check_original(conn, bid, different)
    assert result["passes"] is True
    assert result["containment"] == 0.0


def test_original_is_scoped_to_this_broker_only():
    """Unlike Gate 1's corpus-wide comparison, Gate 3 must never flag a
    draft because it overlaps with a DIFFERENT broker's source prose.
    """
    conn = _conn()
    other_bid = _broker(conn, domain="other.invalid")
    this_bid = _broker(conn, domain="this.invalid")
    from bce.fingerprint import shingle_hashes

    text = "Sunreef catamarans deliver exceptional bluewater comfort for owners today"
    for h in shingle_hashes(text):
        conn.execute(
            "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) "
            "VALUES (?, ?)", (other_bid, h),
        )
    conn.commit()

    result = originality.check_original(conn, this_bid, text)
    assert result["passes"] is True
    assert result["containment"] is None


def test_originality_max_containment_constant_documented_as_first_estimate():
    assert 0.0 < originality.ORIGINALITY_MAX_CONTAINMENT <= 1.0


# --- run_gates: the combining orchestrator ----------------------------------


def _profiled_conn():
    conn = _conn()
    bid = _broker(conn)
    return conn, bid


def test_run_gates_all_pass_returns_overall_pass():
    conn, bid = _profiled_conn()
    result = originality.run_gates(
        conn, broker_id=bid, format="medium", body="Short sentence here. " * 100,
        profile={**PROFILE, "typical_word_count": 300, "avg_sentence_len": 3.0,
                 "structure_pattern": {}},
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )
    assert bool(result) is True
    assert result.passes_uniqueness is True
    assert result.passes_originality is True


def test_run_gates_long_is_never_blocked_by_a_wildly_off_tailored_score():
    """The critical v0.6 interaction the brief calls out: a long/pillar
    draft against a broker whose typical_word_count is nowhere near 2000-
    2300 words must still pass overall, because Gate 2 is not blocking for
    `long` (spec v0.6 §5).
    """
    conn, bid = _profiled_conn()
    long_body = "word " * 2100  # a pillar-length draft
    off_profile = {**PROFILE, "typical_word_count": 477, "avg_sentence_len": 8.0,
                   "structure_pattern": {"paragraphs_per_article": 4, "words_per_paragraph": 60}}

    result = originality.run_gates(
        conn, broker_id=bid, format="long", body=long_body, profile=off_profile,
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )

    # The score itself is genuinely low (proves the test isn't vacuous)...
    assert result.tailored_score < 0.3
    assert result.passes_tailored is False
    # ...but it never blocks the overall verdict for `long`.
    assert bool(result) is True


def test_run_gates_medium_is_blocked_by_a_failing_tailored_score():
    conn, bid = _profiled_conn()
    body = "word " * 5000  # wildly longer than typical_word_count
    off_profile = {**PROFILE, "typical_word_count": 300, "avg_sentence_len": 3.0,
                   "structure_pattern": {}}

    result = originality.run_gates(
        conn, broker_id=bid, format="medium", body=body, profile=off_profile,
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )

    assert result.passes_tailored is False
    assert bool(result) is False


def test_run_gates_short_is_blocked_by_a_failing_tailored_score():
    conn, bid = _profiled_conn()
    body = "word " * 5000
    off_profile = {**PROFILE, "typical_word_count": 100, "avg_sentence_len": 3.0,
                   "structure_pattern": {}}

    result = originality.run_gates(
        conn, broker_id=bid, format="short", body=body, profile=off_profile,
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )

    assert result.passes_tailored is False
    assert bool(result) is False


def test_run_gates_fails_overall_when_uniqueness_fails_regardless_of_format():
    conn, bid = _profiled_conn()
    _insert_draft(conn, format="long", embedding=[1.0, 0.0, 0.0], angle_id=(
        conn.execute("INSERT INTO angle (broker_id, title) VALUES (?, 'A2')", (bid,)).lastrowid
    ))

    result = originality.run_gates(
        conn, broker_id=bid, format="long", body="word " * 2100, profile=PROFILE,
        embedding_client=FakeEmbeddingClient(vector=(1.0, 0.0, 0.0)),
    )

    assert result.passes_uniqueness is False
    assert bool(result) is False


def test_run_gates_fails_overall_when_original_fails_even_for_long():
    conn, bid = _profiled_conn()
    from bce.fingerprint import shingle_hashes

    source_text = "word " * 2100
    for h in shingle_hashes(source_text):
        conn.execute(
            "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) "
            "VALUES (?, ?)", (bid, h),
        )
    conn.commit()

    result = originality.run_gates(
        conn, broker_id=bid, format="long", body=source_text, profile=PROFILE,
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )

    assert result.passes_originality is False
    assert bool(result) is False


def test_run_gates_persists_the_embedding_on_the_result_even_when_it_fails():
    """Spec §10.3: 'a draft rejected for similarity still counts as seen' --
    `run_gates` must hand back the embedding it computed regardless of
    overall pass/fail, so the caller can persist it either way.
    """
    conn, bid = _profiled_conn()
    result = originality.run_gates(
        conn, broker_id=bid, format="long", body="word " * 2100, profile=PROFILE,
        embedding_client=FakeEmbeddingClient(vector=(1, 0, 0)),
    )
    assert result.embedding == [1.0, 0.0, 0.0]


def test_gate_result_is_a_frozen_dataclass_with_explicit_bool():
    import dataclasses

    assert dataclasses.is_dataclass(originality.GateResult)
    result = originality.GateResult(
        passes=False, passes_uniqueness=False, max_similarity=None,
        most_similar_draft_id=None, embedding=None, passes_tailored=False,
        tailored_score=0.0, passes_originality=False, originality_overlap=None,
    )
    try:
        result.passes = True
        assert False, "GateResult must be frozen"
    except dataclasses.FrozenInstanceError:
        pass
    assert bool(result) is False


def test_uncomparable_tailored_score_does_not_block_medium_or_short():
    """The gate that blocks medium/short must not fire on an absence of data.

    Pairs with test_tailored_score_is_none_when_the_profile_has_nothing_to
    _compare: that one pins the score, this one pins the consequence, because
    the score being None is only useful if `run_gates` acts on it correctly.
    """
    conn = _conn()
    bid = _broker(conn, domain="uncomparable.invalid")

    for fmt in ("medium", "short"):
        result = originality.run_gates(
            conn,
            broker_id=bid,
            format=fmt,
            body="A draft with no profile statistics to compare against.",
            profile={},
            embedding_client=FakeEmbeddingClient(vector=(1.0, 0.0, 0.0)),
        )
        assert result.tailored_score is None, fmt
        assert result.passes is True, f"{fmt} blocked by an absent comparison"
