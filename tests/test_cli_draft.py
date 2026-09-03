import json

from bce import cli, db, discover, drafting


def _db(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    return str(p)


def _broker(conn, domain, name=None):
    name = name or domain.split(".")[0].title()
    discover.import_csv(conn, f"name,domain\n{name},{domain}\n")
    bid = conn.execute("SELECT id FROM broker WHERE domain=?", (domain,)).fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return bid


def _profile(conn, bid, register="warm professional"):
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, structure_pattern, "
        "vocabulary_markers, themes, sample_quotes) VALUES (?,?,?,?,?,?)",
        (bid, register, json.dumps({}), json.dumps([]), json.dumps([]), json.dumps([])),
    )
    conn.commit()
    _persist_fixture_fingerprints(conn, bid)

#: Every profiled broker has source fingerprints in production:
#: `profile.profile_broker` refuses to write a profile below
#: MIN_CORPUS_CHARS and persists fingerprints unconditionally once a corpus
#: exists. A fixture that writes a voice_profile without them builds a state
#: production cannot reach, and since `check_original` fails closed on
#: missing fingerprints (§10.9) it would fail the Original gate for a reason
#: unrelated to the test. Text shares no 6-word shingle with any draft body
#: here, so containment is ~0.
_FIXTURE_SOURCE_TEXT = (
    "Antique cartography of the Baltic littoral remains poorly catalogued "
    "in municipal archives despite repeated funding appeals. "
) * 4


def _persist_fixture_fingerprints(conn, broker_id):
    from bce.fingerprint import shingle_hashes

    for h in shingle_hashes(_FIXTURE_SOURCE_TEXT):
        conn.execute(
            "INSERT OR IGNORE INTO source_fingerprint (broker_id, shingle_hash) "
            "VALUES (?, ?)",
            (broker_id, h),
        )
    conn.commit()



def _drafted(conn, bid):
    """A degraded draft: long draft written, short condensation never landed."""
    aid = conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (?, 'T')", (bid,)
    ).lastrowid
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (?, 'body', 'long')", (aid,)
    )
    conn.commit()
    return aid


def _drafted_complete(conn, bid):
    """A fully-drafted broker: both long and short rows under one angle."""
    aid = conn.execute(
        "INSERT INTO angle (broker_id, title) VALUES (?, 'T')", (bid,)
    ).lastrowid
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (?, 'body', 'long')", (aid,)
    )
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, format) VALUES (?, 'blurb', 'short')", (aid,)
    )
    conn.commit()
    return aid


# --- discover.undrafted_brokers ---------------------------------------------


def test_undrafted_brokers_excludes_unprofiled_and_already_drafted(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    a = _broker(conn, "a.invalid")   # profiled, no draft -> included
    b = _broker(conn, "b.invalid")   # not profiled -> excluded
    c = _broker(conn, "c.invalid")   # profiled and drafted -> excluded
    _profile(conn, a)
    _profile(conn, c)
    _drafted(conn, c)

    domains = [r["domain"] for r in discover.undrafted_brokers(conn, 10)]
    assert domains == ["a.invalid"]


def test_undrafted_brokers_respects_limit(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(5):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)
    assert len(discover.undrafted_brokers(conn, 2)) == 2


def test_undrafted_brokers_negative_limit_is_unbounded_in_sqlite(tmp_path):
    """The mechanism the CLI guard exists to stop, asserted directly (mirrors C2)."""
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(12):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)
    assert len(discover.undrafted_brokers(conn, -1)) == 12


# --- F4: undrafted_brokers must not select a broker pulled from the working
# --- set (qualified reset to NULL) even though its profile row survives ----


def test_undrafted_brokers_excludes_a_disqualified_broker(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    a = _broker(conn, "a.invalid")
    _profile(conn, a)
    # requalify clears `qualified` but leaves voice_profile intact (I5).
    conn.execute("UPDATE broker SET qualified=NULL WHERE id=?", (a,))
    conn.commit()

    assert discover.undrafted_brokers(conn, 10) == []


# --- F3: undrafted_brokers orders warmest-first (spec §4), same as
# --- unprofiled_brokers, not alphabetically -------------------------------


def test_undrafted_brokers_orders_warmest_first(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    # Alphabetically "Alpha" < "Zulu", but affinity must win: lists_inventory
    # before mentions before unknown/none, regardless of name.
    alpha = _broker(conn, "alpha.invalid", "Alpha")
    zulu = _broker(conn, "zulu.invalid", "Zulu")
    _profile(conn, alpha)
    _profile(conn, zulu)
    conn.execute("UPDATE broker SET sunreef_affinity='none' WHERE id=?", (alpha,))
    conn.execute("UPDATE broker SET sunreef_affinity='lists_inventory' WHERE id=?", (zulu,))
    conn.commit()

    domains = [r["domain"] for r in discover.undrafted_brokers(conn, 10)]
    assert domains == ["zulu.invalid", "alpha.invalid"]


def test_undrafted_brokers_still_returns_every_eligible_broker_regardless_of_affinity(
    tmp_path,
):
    """Affinity is ordering-only (spec §2/§4): every eligible broker must
    still come back, whatever its affinity, with no filter or threshold.
    """
    path = _db(tmp_path)
    conn = db.connect(path)
    affinities = ["lists_inventory", "mentions", "unknown", "none"]
    ids = []
    for i, affinity in enumerate(affinities):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)
        conn.execute("UPDATE broker SET sunreef_affinity=? WHERE id=?", (affinity, bid))
        ids.append(bid)
    conn.commit()

    domains = {r["domain"] for r in discover.undrafted_brokers(conn, 10)}
    assert domains == {f"b{i}.invalid" for i in range(4)}


# --- F1: clear_drafts / redraft ---------------------------------------------


def test_clear_drafts_for_one_domain_clears_angle_and_draft_rows(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid")
    _profile(conn, bid)
    _drafted(conn, bid)

    assert discover.clear_drafts(conn, domain="https://www.a.invalid/") == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0
    # the broker is selectable again -- voice_profile is untouched
    assert [r["domain"] for r in discover.undrafted_brokers(conn, 10)] == ["a.invalid"]


def test_clear_drafts_for_one_domain_clears_a_fully_drafted_broker_too(tmp_path):
    """Explicit domain clears unconditionally, even a fully-succeeded draft --
    a deliberate operator action, not something the bulk (no-domain) path
    would ever do on its own (spec §11.5: retries are deliberate).
    """
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid")
    _profile(conn, bid)
    _drafted_complete(conn, bid)

    assert discover.clear_drafts(conn, domain="a.invalid") == 1
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 0


def test_clear_drafts_with_no_domain_clears_only_degraded_brokers(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    degraded = _broker(conn, "degraded.invalid")
    complete = _broker(conn, "complete.invalid")
    _profile(conn, degraded)
    _profile(conn, complete)
    _drafted(conn, degraded)             # long only
    _drafted_complete(conn, complete)    # long + short

    assert discover.clear_drafts(conn) == 1
    # the complete broker's two draft rows survive untouched
    assert conn.execute("SELECT COUNT(*) AS c FROM draft").fetchone()["c"] == 2
    undrafted = [r["domain"] for r in discover.undrafted_brokers(conn, 10)]
    assert undrafted == ["degraded.invalid"]


def test_clear_drafts_returns_zero_for_unknown_domain(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    assert discover.clear_drafts(conn, domain="nope.invalid") == 0


def test_redraft_one_domain(tmp_path, capsys):
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid")
    _profile(conn, bid)
    _drafted(conn, bid)

    assert cli.cmd_redraft(path, "https://www.a.invalid/") == 0
    assert "cleared 1" in capsys.readouterr().out
    conn = db.connect(path)
    assert [r["domain"] for r in discover.undrafted_brokers(conn, 10)] == ["a.invalid"]


def test_redraft_all_degraded(tmp_path, capsys):
    path = _db(tmp_path)
    conn = db.connect(path)
    degraded = _broker(conn, "degraded.invalid")
    complete = _broker(conn, "complete.invalid")
    _profile(conn, degraded)
    _profile(conn, complete)
    _drafted(conn, degraded)
    _drafted_complete(conn, complete)

    assert cli.cmd_redraft(path) == 0
    assert "cleared 1" in capsys.readouterr().out
    conn = db.connect(path)
    assert [r["domain"] for r in discover.undrafted_brokers(conn, 10)] == ["degraded.invalid"]


def test_redraft_unknown_domain_returns_1(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_redraft(path, "nope.invalid") == 1
    assert "no draft found" in capsys.readouterr().out


def test_redraft_with_nothing_degraded_returns_0(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_redraft(path) == 0
    assert "no degraded drafts" in capsys.readouterr().out


def test_main_routes_redraft(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "redraft"]) == 0


# --- cli.cmd_draft: ceiling ---------------------------------------------------


def test_max_draft_calls_lowered_for_the_fourth_call_per_broker():
    """Spec v0.6 §5/§11.5: each broker drafted now costs four Claude calls
    (angles, long, medium, short) instead of three. The session call budget
    (the old MAX_DRAFT_CALLS=10 brokers * 3 calls/broker = 30 calls) is kept
    roughly constant rather than silently tripled -- 30 // 4 = 7 brokers, so
    the ceiling actually drops with a fourth call, not just "grows more slowly".
    """
    assert cli.MAX_DRAFT_CALLS == 7


def test_draft_refuses_a_limit_over_the_ceiling(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS + 1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_draft_refuses_a_negative_limit_and_builds_nothing(tmp_path, capsys, monkeypatch):
    path = _db(tmp_path)
    conn = db.connect(path)
    for i in range(12):
        bid = _broker(conn, f"b{i}.invalid")
        _profile(conn, bid)

    def _boom(*a, **k):
        raise AssertionError("no client should be constructed on refusal")

    monkeypatch.setattr(cli, "AngleClient", _boom)
    monkeypatch.setattr(cli, "DraftClient", _boom)

    rc = cli.cmd_draft(path, limit=-1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()
    assert conn.execute("SELECT COUNT(*) AS c FROM angle").fetchone()["c"] == 0


def test_draft_refuses_a_zero_limit(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_draft(path, limit=0)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_draft_ceiling_refusal_explains_four_calls_per_broker(tmp_path, capsys):
    """Spec v0.6 §5: a third draft format (medium) means a fourth Claude call
    per broker -- angles, long, medium, short -- so the refusal message must
    say "four", not the old "three".
    """
    path = _db(tmp_path)
    cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS + 1)
    out = capsys.readouterr().out.lower()
    assert "four" in out
    assert "call" in out


def test_draft_at_the_ceiling_is_allowed(tmp_path):
    path = _db(tmp_path)
    # No profiled-but-undrafted brokers, so nothing is drafted and no API
    # client is built (would otherwise need ANTHROPIC_API_KEY).
    assert cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS) == 0


def test_draft_with_nothing_to_do_prints_a_message(tmp_path, capsys):
    path = _db(tmp_path)
    assert cli.cmd_draft(path) == 0
    assert "no" in capsys.readouterr().out.lower()


# --- cli.cmd_draft: happy path, with fake clients (no network / API key) -----


class _FakeAngleClient:
    def __init__(self):
        self.calls = 0

    def propose(self, profile, broker_name):
        self.calls += 1
        return [
            {
                "title": "An angle",
                "premise": "p",
                "audience_value": "v",
                "sunreef_relevance": "r",
                "score": 0.7,
            }
        ]


class _FakeDraftClient:
    """Bodies are deliberately over SHINGLE_SIZE (6) words. Two-word stand-ins
    produce no shingles at all, and since 2026-09-02 the Original gate fails
    closed when it cannot compare (§10.9) -- so a too-short fixture would be
    rejected for its length rather than exercising what this test is about.
    No real format is that short; §5's shortest is 100-200 words.
    """

    def write_long(self, angle, profile, broker_name, keywords=None):
        return "Long body with enough words in it to shingle properly."

    def write_medium(self, long_body, profile, broker_name, keywords=None):
        return "Medium body with enough words in it to shingle properly."

    def write_short(self, long_body, profile, keywords=None):
        return "Short body with enough words in it to shingle properly."


class _FakeEmbeddingClient:
    def embed(self, text):
        return [1.0, 0.0, 0.0]


class _DeadEmbeddingClient:
    """An embedding client that cannot produce a vector -- what the real one
    degrades to with no `VOYAGE_API_KEY`, no network, or an API error.
    """

    def embed(self, text):
        return None


def test_draft_drives_undrafted_brokers_and_prints_a_line_per_broker(
    tmp_path, capsys, monkeypatch
):
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid", "Acme")
    _profile(conn, bid)

    monkeypatch.setattr(cli, "AngleClient", _FakeAngleClient)
    monkeypatch.setattr(cli, "DraftClient", _FakeDraftClient)
    monkeypatch.setattr(cli, "EmbeddingClient", _FakeEmbeddingClient)

    rc = cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS)
    assert rc == 0
    out = capsys.readouterr().out
    assert "a.invalid" in out

    conn = db.connect(path)
    drafts = conn.execute("SELECT format, status FROM draft").fetchall()
    assert {d["format"] for d in drafts} == {"long", "medium", "short"}
    assert all(d["status"] == "pending_review" for d in drafts)


def test_draft_without_a_working_embedding_client_rejects_every_draft(
    tmp_path, capsys, monkeypatch
):
    """No VOYAGE_API_KEY means uniqueness cannot be verified, and §10.3's
    uniqueness gate is blocking. "We could not check" must not be treated as
    "we checked and it is fine", so every draft lands `rejected` rather than
    reaching the review queue.

    This is the CLI's real behaviour with no key configured, pinned here
    deliberately: it is the difference between a silent quality hole and an
    obvious one.
    """
    path = _db(tmp_path)
    conn = db.connect(path)
    bid = _broker(conn, "a.invalid", "Acme")
    _profile(conn, bid)

    monkeypatch.setattr(cli, "AngleClient", _FakeAngleClient)
    monkeypatch.setattr(cli, "DraftClient", _FakeDraftClient)
    monkeypatch.setattr(cli, "EmbeddingClient", _DeadEmbeddingClient)

    assert cli.cmd_draft(path, limit=cli.MAX_DRAFT_CALLS) == 0

    conn = db.connect(path)
    rows = conn.execute("SELECT status, passes_uniqueness, embedding FROM draft").fetchall()
    assert rows, "drafts should still be written, just not approved"
    assert all(r["status"] == "rejected" for r in rows)
    assert all(r["passes_uniqueness"] == 0 for r in rows)
    # Nothing to persist when the vector was never computed.
    assert all(r["embedding"] is None for r in rows)


def test_main_dispatches_draft(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "draft", "--limit", "1"]) == 0
