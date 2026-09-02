"""Keyword persistence in `drafting.draft_for_broker` (spec §5b/§8): the
selected primary/secondary keywords are written as `draft_keyword` rows in
the same transaction as the `draft` row itself, and existing partial-failure
semantics (long fails -> nothing written; medium/short fail independently)
must hold exactly as before.

Fixtures are built inline via direct `INSERT INTO keyword` statements, never
through `bce.seed` -- seeding keywords onto example drafts is a separate,
later task per the brief, and `seed.py` is off-limits here regardless.
"""
import json

from bce import db, discover, drafting

# --- fakes (mirror test_drafting.py's, with keywords captured) --------------


class FakeEmbeddingClient:
    """Mirrors `bce.embeddings.EmbeddingClient`'s public shape (`.embed`).

    Defined locally rather than imported from test_drafting.py: these tests
    are about keyword persistence, not the gates, so they want an embedding
    client that is deliberately boring. A constant vector means the first
    draft in each format bucket has nothing to collide with and the gates
    stay out of the way of what is being asserted here.
    """

    def __init__(self, vector=(1.0, 0.0, 0.0)):
        self.vector = vector

    def embed(self, text):
        return list(self.vector)


class FakeAngleClient:
    def __init__(self, angles=None):
        self.angles = [] if angles is None else angles

    def propose(self, profile, broker_name):
        return self.angles


class FakeDraftClient:
    def __init__(self, long_body="Long body.", medium_body="Medium body.",
                 short_body="Short body."):
        self.long_body = long_body
        self.medium_body = medium_body
        self.short_body = short_body
        self.long_calls = []
        self.medium_calls = []
        self.short_calls = []

    def write_long(self, angle, profile, broker_name, keywords=None):
        self.long_calls.append({"keywords": keywords})
        return self.long_body

    def write_medium(self, long_body, profile, broker_name, keywords=None):
        self.medium_calls.append({"keywords": keywords})
        return self.medium_body

    def write_short(self, long_body, profile, keywords=None):
        self.short_calls.append({"keywords": keywords})
        return self.short_body


ANGLE = {
    "title": "What a Catamaran For Sale Actually Costs",
    "premise": "Buyers price a catamaran for sale against the sticker.",
    "audience_value": "Helps first-time buyers budget with eyes open.",
    "sunreef_relevance": "Names a Sunreef layout in passing.",
}


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def _broker(conn, domain="acme.invalid", name="Acme"):
    discover.import_csv(conn, f"name,domain\n{name},{domain}\n")
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return bid


def _profiled_broker(conn):
    bid = _broker(conn)
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            bid, "warm professional", 18.5, 850,
            json.dumps({"paragraphs_per_article": 6, "words_per_paragraph": 120}),
            json.dumps(["berth", "passage"]),
            json.dumps(["catamaran ownership"]),
            "prospective owners",
            json.dumps([]),
        ),
    )
    conn.commit()
    return bid


def _insert_keyword(conn, phrase, volume, difficulty, *, competitor_brand=0):
    """Defaults to fully selectable (segment_relevant=1, editorial=1) -- this
    file tests draft/draft_keyword persistence wiring, not the segment-
    relevance or editorial-intent gates themselves (see test_keywords_
    segment.py / test_keywords_editorial.py), so the fixture must not
    accidentally fail selection through `editorial`'s conservative
    (non-editorial) schema default.
    """
    from bce import keywords as kw_module

    q = 1 if kw_module.qualifies(volume, difficulty) else 0
    cursor = conn.execute(
        "INSERT INTO keyword (phrase, volume, difficulty, database, "
        "measured_at, qualifies, source, competitor_brand, segment_relevant, "
        "editorial) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (phrase, volume, difficulty, "us", "2026-09-01", q, "semrush",
         competitor_brand, 1, 1),
    )
    conn.commit()
    return cursor.lastrowid


def _seed_healthy_bank(conn):
    ids = {
        "catamaran for sale": _insert_keyword(conn, "catamaran for sale", 8100, 25),
        "catamarans for sale": _insert_keyword(conn, "catamarans for sale", 4400, 24),
        "power catamaran for sale": _insert_keyword(conn, "power catamaran for sale", 2400, 17),
        "what is a catamaran": _insert_keyword(conn, "what is a catamaran", 1900, 25),
        "yacht refit": _insert_keyword(conn, "yacht refit", 1900, 10),
        "power catamaran": _insert_keyword(conn, "power catamaran", 1600, 28),
        "catamaran club": _insert_keyword(conn, "catamaran club", 1000, 20),
    }
    return ids


# --- keywords actually get baked in --------------------------------------


def test_draft_keywords_are_persisted_for_the_long_draft():
    conn = _conn()
    bid = _profiled_broker(conn)
    _seed_healthy_bank(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    long_draft_id = conn.execute(
        "SELECT id FROM draft WHERE format='long'"
    ).fetchone()["id"]
    rows = conn.execute(
        "SELECT role, keyword_id FROM draft_keyword WHERE draft_id=? ORDER BY role",
        (long_draft_id,),
    ).fetchall()
    roles = [r["role"] for r in rows]
    assert "primary" in roles
    assert roles.count("primary") == 1
    assert len(rows) == 5  # 1 primary + up to 4 secondary, healthy bank has enough


def test_draft_keywords_persisted_for_medium_and_short_are_a_subset_of_longs():
    conn = _conn()
    bid = _profiled_broker(conn)
    _seed_healthy_bank(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    def _keyword_ids(fmt):
        draft_id = conn.execute(
            "SELECT id FROM draft WHERE format=?", (fmt,)
        ).fetchone()["id"]
        return {
            r["keyword_id"]
            for r in conn.execute(
                "SELECT keyword_id FROM draft_keyword WHERE draft_id=?", (draft_id,)
            )
        }

    long_ids = _keyword_ids("long")
    medium_ids = _keyword_ids("medium")
    short_ids = _keyword_ids("short")
    assert medium_ids <= long_ids
    assert short_ids <= long_ids
    assert len(medium_ids) == 3  # 1 primary + 2 secondary
    assert len(short_ids) == 1  # 1 primary only


def test_draft_clients_receive_the_same_selection_that_gets_persisted():
    """Not just 'something got saved' -- the exact selection passed into the
    prompt (via `keywords=`) must be the same one persisted as draft_keyword
    rows, so the UI panel and the prompt never disagree about what's baked in.
    """
    conn = _conn()
    bid = _profiled_broker(conn)
    _seed_healthy_bank(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    sent_primary_phrase = draft_client.long_calls[0]["keywords"]["primary"]["phrase"]
    long_draft_id = conn.execute("SELECT id FROM draft WHERE format='long'").fetchone()["id"]
    persisted_primary_id = conn.execute(
        "SELECT keyword_id FROM draft_keyword WHERE draft_id=? AND role='primary'",
        (long_draft_id,),
    ).fetchone()["keyword_id"]
    persisted_phrase = conn.execute(
        "SELECT phrase FROM keyword WHERE id=?", (persisted_primary_id,)
    ).fetchone()["phrase"]
    assert sent_primary_phrase == persisted_phrase


# --- empty bank / nothing qualifies: draft still writes, no keyword rows ----


def test_draft_writes_normally_when_nothing_qualifies():
    """Spec §5b: 'If no banked keyword clears both thresholds ... the draft
    is still written' -- an empty keyword table must not block drafting or
    raise, and no draft_keyword rows get written.
    """
    conn = _conn()
    bid = _profiled_broker(conn)  # no keywords seeded at all
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 3
    assert conn.execute("SELECT COUNT(*) AS c FROM draft_keyword").fetchone()["c"] == 0
    assert draft_client.long_calls[0]["keywords"] == {"primary": None, "secondary": []}


def test_draft_writes_normally_when_only_competitor_gated_keywords_exist():
    conn = _conn()
    bid = _profiled_broker(conn)
    _insert_keyword(conn, "lagoon catamaran", 2400, 26, competitor_brand=1)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient()

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert conn.execute("SELECT COUNT(*) AS c FROM draft_keyword").fetchone()["c"] == 0


# --- partial-failure semantics are preserved exactly -------------------------


def test_long_failure_persists_no_keywords_at_all():
    conn = _conn()
    bid = _profiled_broker(conn)
    _seed_healthy_bank(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(long_body=None)

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is False
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM draft_keyword").fetchone()["c"] == 0


def test_medium_failure_still_persists_keywords_for_long_and_short():
    conn = _conn()
    bid = _profiled_broker(conn)
    _seed_healthy_bank(conn)
    angle_client = FakeAngleClient(angles=[ANGLE])
    draft_client = FakeDraftClient(medium_body=None)

    result = drafting.draft_for_broker(conn, bid, angle_client, draft_client, FakeEmbeddingClient())

    assert bool(result) is True
    assert result.medium_written is False
    long_draft_id = conn.execute("SELECT id FROM draft WHERE format='long'").fetchone()["id"]
    short_draft_id = conn.execute("SELECT id FROM draft WHERE format='short'").fetchone()["id"]
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM draft_keyword WHERE draft_id=?", (long_draft_id,)
    ).fetchone()["c"] > 0
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM draft_keyword WHERE draft_id=?", (short_draft_id,)
    ).fetchone()["c"] > 0
    # No medium draft row exists at all, so nothing can reference it.
    assert conn.execute("SELECT COUNT(*) AS c FROM draft WHERE format='medium'").fetchone()["c"] == 0
