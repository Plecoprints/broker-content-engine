import json

from bce import db, discover, drafting

# --- fakes ---------------------------------------------------------------
#
# These mirror `angles.AngleClient` / `draft.DraftClient`'s public shape
# (`.propose`, `.write_long`, `.write_short`) but record exactly what they
# were called with, so tests can assert on the *actual* argument values
# rather than trusting that "no exception was raised" means the seam is
# correct -- that is the class of defect this task exists to catch (see
# task-6-brief.md: a `sqlite3.Row`'s JSON-string columns passed straight
# through would not raise, it would just condition every draft on JSON
# punctuation).


class FakeAngleClient:
    def __init__(self, angles=None):
        self.angles = [] if angles is None else angles
        self.calls = []

    def propose(self, profile, broker_name):
        self.calls.append({"profile": profile, "broker_name": broker_name})
        return self.angles


class FakeDraftClient:
    """Mirrors `draft.DraftClient`'s public shape, including the optional
    `keywords=` kwarg (spec §5b) each `write_*` now accepts -- captured here
    (not just accepted) so tests can assert on exactly what selection the
    orchestrator passed through for each format.
    """

    def __init__(self, long_body="Long body.", medium_body="Medium body.",
                 short_body="Short body."):
        self.long_body = long_body
        self.medium_body = medium_body
        self.short_body = short_body
        self.long_calls = []
        self.medium_calls = []
        self.short_calls = []

    def write_long(self, angle, profile, broker_name, keywords=None):
        self.long_calls.append(
            {"angle": angle, "profile": profile, "broker_name": broker_name,
             "keywords": keywords}
        )
        return self.long_body

    def write_medium(self, long_body, profile, broker_name, keywords=None):
        self.medium_calls.append(
            {"long_body": long_body, "profile": profile, "broker_name": broker_name,
             "keywords": keywords}
        )
        return self.medium_body

    def write_short(self, long_body, profile, keywords=None):
        self.short_calls.append(
            {"long_body": long_body, "profile": profile, "keywords": keywords}
        )
        return self.short_body


class FakeEmbeddingClient:
    """Mirrors `bce.embeddings.EmbeddingClient`'s public shape (`.embed`).
    Returns a caller-controlled vector for *every* input by default -- fine
    for tests that only care that gate columns get populated -- but a test
    that needs to force a specific cosine similarity (e.g. "these two
    drafts collide") can pass `vectors_by_body` to hand back a different
    vector per exact body string.
    """

    def __init__(self, vector=(1.0, 0.0, 0.0), vectors_by_body=None):
        self.vector = vector
        self.vectors_by_body = vectors_by_body or {}
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if text in self.vectors_by_body:
            return list(self.vectors_by_body[text])
        if self.vector is None:
            return None
        return list(self.vector)


ANGLE = {
    "title": "Provisioning for a Two-Week Mediterranean Crossing",
    "premise": "What owners actually pack, versus what the checklists say.",
    "audience_value": "Helps prospective owners plan a realistic first passage.",
    "sunreef_relevance": "Mentions catamaran galley storage in passing.",
    "score": 0.8,
}


def _broker(conn, domain="acme.invalid", name="Acme"):
    discover.import_csv(conn, f"name,domain\n{name},{domain}\n")
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return bid


def _profiled_broker(conn, *, register="warm professional", **overrides):
    """A broker with a voice_profile row stored exactly as `profile_broker`
    would store it -- the four structured columns as JSON *strings*, since
    that is the real on-disk shape this orchestrator must deserialize.
    """
    bid = _broker(conn)
    values = {
        "register": register,
        "avg_sentence_len": 18.5,
        "typical_word_count": 850,
        "structure_pattern": json.dumps(
            {"paragraphs_per_article": 6, "words_per_paragraph": 120}
        ),
        "vocabulary_markers": json.dumps(["berth", "passage", "charter"]),
        "themes": json.dumps(["catamaran ownership", "charter management"]),
        "audience_signal": "prospective owners",
        "sample_quotes": json.dumps(["Draft is the constraint nobody mentions."]),
    }
    values.update(overrides)
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            bid,
            values["register"],
            values["avg_sentence_len"],
            values["typical_word_count"],
            values["structure_pattern"],
            values["vocabulary_markers"],
            values["themes"],
            values["audience_signal"],
            values["sample_quotes"],
        ),
    )
    conn.commit()
    return bid


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


# --- the seam: deserialized structures reach the clients --------------------


def test_clients_receive_parsed_structures_not_json_strings():
    """The exact defect named in the brief: a raw sqlite3.Row would pass a
    JSON *string* through unchanged, which would not raise but would
    condition every draft on JSON punctuation. Assert on what the fake
    clients actually received.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert len(angle_client.calls) == 1
    angle_profile = angle_client.calls[0]["profile"]
    assert isinstance(angle_profile["themes"], list)
    assert angle_profile["themes"] == ["catamaran ownership", "charter management"]
    assert isinstance(angle_profile["structure_pattern"], dict)
    assert angle_profile["structure_pattern"]["paragraphs_per_article"] == 6
    assert isinstance(angle_profile["vocabulary_markers"], list)

    assert len(draft_client.long_calls) == 1
    long_profile = draft_client.long_calls[0]["profile"]
    assert isinstance(long_profile["themes"], list)
    assert isinstance(long_profile["structure_pattern"], dict)
    assert isinstance(long_profile["vocabulary_markers"], list)

    assert len(draft_client.medium_calls) == 1
    medium_profile = draft_client.medium_calls[0]["profile"]
    assert isinstance(medium_profile["themes"], list)
    assert isinstance(medium_profile["structure_pattern"], dict)
    assert isinstance(medium_profile["vocabulary_markers"], list)

    assert len(draft_client.short_calls) == 1
    short_profile = draft_client.short_calls[0]["profile"]
    assert isinstance(short_profile["themes"], list)
    assert isinstance(short_profile["structure_pattern"], dict)


def test_malformed_json_columns_degrade_instead_of_raising():
    """Malformed JSON must not crash the orchestrator (mirrors web/app._loads)."""
    conn = _conn()
    bid = _profiled_broker(
        conn, structure_pattern="{not json", themes="also not json", vocabulary_markers=None
    )
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    profile = angle_client.calls[0]["profile"]
    assert profile["structure_pattern"] == {}
    assert profile["themes"] == []
    assert profile["vocabulary_markers"] == []


# --- behaviours ---------------------------------------------------------


def test_no_voice_profile_writes_nothing_and_makes_no_api_call():
    conn = _conn()
    bid = _broker(conn)  # qualified, but never profiled
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is False
    assert angle_client.calls == []
    assert draft_client.long_calls == []
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0


def test_empty_judgement_profile_is_treated_as_no_usable_profile():
    """register/themes/audience_signal all NULL -- classification failed."""
    conn = _conn()
    bid = _profiled_broker(
        conn, register=None, themes=None, audience_signal=None, vocabulary_markers=None
    )
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is False
    assert angle_client.calls == []
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0


def test_empty_angles_writes_nothing_and_makes_no_further_calls():
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is False
    assert len(angle_client.calls) == 1
    assert draft_client.long_calls == []
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0


def test_none_long_draft_writes_nothing_and_skips_medium_and_short_calls():
    """Spec v0.6 §5: medium and short both condense from the long body, so if
    write_long fails there is nothing for either of them to condense --
    neither call is made, and nothing is written (unchanged from before the
    three-format change, now covering one more client).
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(long_body=None)

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is False
    assert len(draft_client.long_calls) == 1
    assert draft_client.medium_calls == []  # nothing to condense
    assert draft_client.short_calls == []  # nothing to condense
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0


def test_none_medium_draft_still_keeps_the_good_long_and_short_drafts():
    """New in v0.6: medium and short are independent condensation attempts --
    one failing must not discard the long draft or the other condensation.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(
        long_body="A full article body.", medium_body=None, short_body="Short blurb."
    )

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert result.medium_written is False
    assert result.short_written is True
    rows = conn.execute("SELECT * FROM draft ORDER BY format").fetchall()
    formats = {r["format"] for r in rows}
    assert formats == {"long", "short"}


def test_none_short_draft_still_keeps_the_good_long_and_medium_drafts():
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(
        long_body="A full article body.", medium_body="A regular post.", short_body=None
    )

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert result.medium_written is True
    assert result.short_written is False
    rows = conn.execute("SELECT * FROM draft").fetchall()
    formats = {r["format"] for r in rows}
    assert formats == {"long", "medium"}
    long_row = next(r for r in rows if r["format"] == "long")
    assert long_row["body_md"] == "A full article body."
    assert long_row["status"] == "pending_review"


def test_none_medium_and_none_short_still_keeps_the_good_long_draft():
    """Both condensations can fail independently and simultaneously; the
    long draft is kept regardless, and both failures are reported.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(
        long_body="A full article body.", medium_body=None, short_body=None
    )

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert result.medium_written is False
    assert result.short_written is False
    rows = conn.execute("SELECT * FROM draft").fetchall()
    assert len(rows) == 1
    assert rows[0]["format"] == "long"
    assert rows[0]["body_md"] == "A full article body."
    assert rows[0]["status"] == "pending_review"


def test_medium_and_short_are_both_attempted_even_though_short_is_independent():
    """Neither condensation call short-circuits the other: both write_medium
    and write_short are always attempted once write_long succeeds.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(long_body="Long body.")

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert len(draft_client.medium_calls) == 1
    assert len(draft_client.short_calls) == 1
    # Both condense from the long body, not the angle (spec §5).
    assert draft_client.medium_calls[0]["long_body"] == "Long body."
    assert draft_client.short_calls[0]["long_body"] == "Long body."


def test_all_three_drafts_persist_as_three_rows_under_one_angle():
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(
        long_body="Long body.", medium_body="Medium post.", short_body="Short blurb."
    )

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert result.medium_written is True
    assert result.short_written is True

    angles = conn.execute("SELECT * FROM angle").fetchall()
    assert len(angles) == 1
    assert angles[0]["title"] == ANGLE["title"]

    drafts = conn.execute(
        "SELECT * FROM draft ORDER BY format"
    ).fetchall()
    assert len(drafts) == 3
    formats = {d["format"] for d in drafts}
    assert formats == {"long", "medium", "short"}
    for d in drafts:
        assert d["angle_id"] == angles[0]["id"]
        # Changed assertion (was `== "pending_review"` unconditionally):
        # the three originality gates (spec §10.3) now run before status is
        # decided, and these trivially short fake bodies ("Medium post.",
        # "Short blurb.") are nowhere near this broker's typical_word_count
        # (850) -- Gate 2 legitimately rejects them. "pending_review" vs.
        # "rejected" is exactly the gate outcome this file is not testing
        # (see test_originality.py for that, and
        # test_gate_columns_are_populated_on_every_persisted_draft /
        # test_medium_and_short_gate_rejection_still_lands_a_row below for
        # this module's own coverage of it) -- this test's job is only to
        # confirm three rows persist under one angle, so it accepts either
        # legitimate terminal state and never "sent".
        assert d["status"] in ("pending_review", "rejected")
        assert d["reviewed_by"] is None


def test_nothing_ever_writes_status_sent():
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    statuses = {r["status"] for r in conn.execute("SELECT status FROM draft")}
    assert "sent" not in statuses


def test_result_is_a_frozen_dataclass_with_explicit_bool():
    import dataclasses

    assert dataclasses.is_dataclass(drafting.DraftResult)
    assert dataclasses.fields(drafting.DraftResult)  # has fields
    frozen_result = drafting.DraftResult(written=False)
    try:
        frozen_result.written = True
        assert False, "DraftResult must be frozen"
    except dataclasses.FrozenInstanceError:
        pass
    # Truthiness must come from the explicit __bool__, not tuple semantics.
    assert bool(drafting.DraftResult(written=False)) is False
    assert bool(drafting.DraftResult(written=True)) is True


def test_draft_result_defaults_medium_and_short_written_to_false():
    result = drafting.DraftResult(written=True)
    assert result.medium_written is False
    assert result.short_written is False


def test_picks_the_best_scoring_angle():
    conn = _conn()
    bid = _profiled_broker(conn)
    low = {**ANGLE, "title": "Low", "score": 0.2}
    high = {**ANGLE, "title": "High", "score": 0.9}
    angle_client = FakeAngleClient(angles=[low, high])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    stored = conn.execute("SELECT title FROM angle").fetchone()
    assert stored["title"] == "High"
    assert draft_client.long_calls[0]["angle"]["title"] == "High"


def test_gate_four_verdict_and_evidence_persist_on_the_draft_row():
    """§10.4 / §10.9 gate 4 is recorded on every persisted draft, and when it
    fails the offending text is stored with it.

    The evidence matters more here than for the other gates. A similarity
    figure can be recomputed from the stored embedding; a product claim
    cannot be recovered from a verdict, and §10.4's whole difficulty is that
    nobody can verify the claim after the fact. So the text has to survive to
    the row, where a reviewer -- or a redraft -- can see what tripped it.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(
        long_body="The Sunreef 80 Eco carries 46 m2 of solar panels.",
        medium_body="A clean medium post about cruising grounds.",
        short_body="A clean short blurb.",
    )

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    rows = {
        r["format"]: r
        for r in conn.execute("SELECT * FROM draft").fetchall()
    }

    long_row = rows["long"]
    assert long_row["passes_no_product_claims"] == 0
    assert long_row["status"] == "rejected"
    stored = json.loads(long_row["product_claims_found"])
    assert stored[0]["vessel"] == "Sunreef 80 Eco"
    assert stored[0]["claim"] == "46 m2"

    # The clean formats record a pass and store no evidence -- an empty list
    # and NULL are different states, and NULL is "nothing tripped it".
    for fmt in ("medium", "short"):
        assert rows[fmt]["passes_no_product_claims"] == 1
        assert rows[fmt]["product_claims_found"] is None
