from bce import db, discover, seed


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def test_seed_covers_every_display_state():
    conn = _conn()
    n = seed.seed_example(conn)
    assert n >= 7
    rows = discover.list_brokers(conn)
    reasons = {r["qualified_reason"] for r in rows}
    assert {"below_length_threshold", "editorial_recency_undetermined",
            "unreachable_or_disallowed"} <= reasons
    assert any(r["qualified"] is None for r in rows)
    assert any(r["qualified"] == 1 for r in rows)


def test_seed_includes_a_profiled_broker_whose_classification_failed():
    conn = _conn()
    seed.seed_example(conn)
    row = conn.execute(
        "SELECT * FROM voice_profile WHERE register IS NULL"
    ).fetchone()
    assert row is not None
    assert row["avg_sentence_len"] > 0


def test_seed_includes_a_qualified_broker_with_no_profile():
    conn = _conn()
    seed.seed_example(conn)
    row = conn.execute(
        "SELECT b.id FROM broker b LEFT JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND v.broker_id IS NULL"
    ).fetchone()
    assert row is not None


def test_every_seed_domain_is_unresolvable():
    """`.invalid` is reserved by RFC 2606 — seed data can never be crawled."""
    conn = _conn()
    seed.seed_example(conn)
    for row in discover.list_brokers(conn):
        assert row["domain"].endswith(".invalid")


def test_seed_is_idempotent():
    conn = _conn()
    seed.seed_example(conn)
    first = len(discover.list_brokers(conn))
    seed.seed_example(conn)
    assert len(discover.list_brokers(conn)) == first


def test_seed_gives_the_fully_profiled_broker_an_angle_and_both_drafts():
    conn = _conn()
    seed.seed_example(conn)
    broker = conn.execute(
        "SELECT id FROM broker WHERE domain='meridian-yacht.invalid'"
    ).fetchone()
    angle = conn.execute(
        "SELECT * FROM angle WHERE broker_id=?", (broker["id"],)
    ).fetchone()
    assert angle is not None
    assert angle["title"]
    assert angle["premise"]
    assert angle["audience_value"]
    assert angle["sunreef_relevance"]
    assert angle["score"] is not None

    drafts = conn.execute(
        "SELECT * FROM draft WHERE angle_id=?", (angle["id"],)
    ).fetchall()
    formats = {d["format"] for d in drafts}
    assert formats == {"long", "short"}
    for d in drafts:
        assert d["status"] == "pending_review"
        assert d["word_count"] == len(d["body_md"].split())
        # Realistic prose, not filler.
        assert "lorem" not in d["body_md"].lower()
        assert len(d["body_md"].split()) > 50


def test_seed_gives_one_broker_a_long_draft_but_no_short_draft():
    """The degraded state `bce redraft` exists to repair (short condensation failed)."""
    conn = _conn()
    seed.seed_example(conn)
    rows = conn.execute(
        "SELECT a.broker_id, a.id AS angle_id FROM angle a "
        "JOIN draft d ON d.angle_id = a.id AND d.format = 'long' "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM draft d2 WHERE d2.angle_id = a.id AND d2.format = 'short'"
        ")"
    ).fetchall()
    assert len(rows) >= 1
    angle_id = rows[0]["angle_id"]
    long_draft = conn.execute(
        "SELECT * FROM draft WHERE angle_id=? AND format='long'", (angle_id,)
    ).fetchone()
    assert long_draft is not None
    assert len(long_draft["body_md"].split()) > 50
