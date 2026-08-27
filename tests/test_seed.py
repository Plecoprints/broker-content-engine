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
