"""The originality gate panel in the draft viewer (spec §10.3, §9).

Admin-only by design: unlike `_keyword_panel.html`, this partial is NOT
shared with the broker portal (§9b). "Collided at 0.91 with draft #14" is
internal quality assurance -- what an operator needs at review, and what
would undermine a broker's confidence in a draft.
"""
import re

from fastapi.testclient import TestClient

from bce import db, drafting, originality
from bce.web.app import create_app


class _Embedder:
    def __init__(self, vector=(0.3, 0.9, 0.1)):
        self.vector = vector

    def embed(self, text):
        return None if self.vector is None else list(self.vector)


class _Angles:
    def propose(self, profile, broker_name):
        return [{"title": "Refit economics", "premise": "P", "score": 9}]


class _Drafts:
    def write_long(self, angle, profile, broker_name, keywords=None):
        return ("A pillar paragraph about refit costs. " * 40 + "\n\n") * 8

    def write_medium(self, long_body, profile, broker_name, keywords=None):
        return ("A shorter paragraph on the same. " * 20 + "\n\n") * 5

    def write_short(self, long_body, profile, keywords=None):
        return "A newsletter blurb about refit costs. " * 12


def _drafted(tmp_path, embedder=None):
    """A broker with all three formats drafted through the real gates."""
    import json

    path = str(tmp_path / "gates.db")
    conn = db.connect(path)
    db.init_schema(conn)
    bid = conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Acme', 'a.invalid', 'manual')"
    ).lastrowid
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            bid, "warm professional", 7.0, 600,
            json.dumps({"paragraphs_per_article": 5, "words_per_paragraph": 120}),
            json.dumps([]), json.dumps([]), "owners", json.dumps([]),
        ),
    )
    conn.commit()
    drafting.draft_for_broker(
        conn, bid, _Angles(), _Drafts(), embedder or _Embedder()
    )
    conn.commit()
    conn.close()
    return path, bid


def test_gate_panel_shows_a_verdict_for_all_three_gates(tmp_path):
    path, bid = _drafted(tmp_path)
    body = TestClient(create_app(path)).get(f"/broker/{bid}/drafts").text

    assert "Originality gates" in body
    for gate in ("Unique", "Tailored", "Original"):
        assert gate in body, gate


def test_gate_panel_never_leaks_a_literal_none(tmp_path):
    """Follows the existing guard pattern: NULL similarity/overlap/score are
    all reachable states (nothing to compare against yet), and each must
    render as prose, never as Python's repr.
    """
    path, bid = _drafted(tmp_path)
    body = TestClient(create_app(path)).get(f"/broker/{bid}/drafts").text
    assert "None" not in body


def test_a_long_draft_failing_voice_match_is_not_rejected_and_says_why(tmp_path):
    """Spec v0.6 §5: voice matching is encouraged but not binding for the
    pillar format, because no broker's typical_word_count is near 2,000
    words. The panel must both leave the draft queued and explain the
    asymmetry, or an operator reading "Tailored: fail" on an accepted draft
    would reasonably think the gate was broken.
    """
    path, bid = _drafted(tmp_path)
    conn = db.connect(path)
    long_row = conn.execute(
        "SELECT status, passes_tailored FROM draft WHERE format='long'"
    ).fetchone()

    assert long_row["passes_tailored"] == 0, (
        "fixture no longer exercises the case: the long draft passes voice "
        "match, so this test would pass vacuously"
    )
    assert long_row["status"] == "pending_review"

    body = TestClient(create_app(path)).get(f"/broker/{bid}/drafts").text
    # Collapse whitespace first: the phrase wraps across lines in the
    # template, so a raw substring check would fail on indentation rather
    # than on the behaviour under test.
    assert "not held to the broker" in re.sub(r"\s+", " ", body)


def test_gate_panel_says_unverified_rather_than_clean_when_embedding_failed(tmp_path):
    """A blocking gate that degrades to "fine" when it could not run is worse
    than no gate. With no embedding the panel must say so explicitly.
    """
    path, bid = _drafted(tmp_path, embedder=_Embedder(vector=None))
    body = TestClient(create_app(path)).get(f"/broker/{bid}/drafts").text

    assert "Could not be checked" in body
    assert "not treated as clean" in body

    conn = db.connect(path)
    statuses = {r["status"] for r in conn.execute("SELECT status FROM draft")}
    assert statuses == {"rejected"}


def test_uniqueness_threshold_reaches_the_template(tmp_path):
    """The panel states the bar a draft was judged against. Hardcoding it in
    the template would let it drift silently from the constant that actually
    decides the verdict.
    """
    path, bid = _drafted(tmp_path)
    # Force a collision so the threshold is rendered alongside the figure.
    conn = db.connect(path)
    conn.execute("UPDATE draft SET max_similarity=0.95 WHERE format='long'")
    conn.commit()
    conn.close()

    body = TestClient(create_app(path)).get(f"/broker/{bid}/drafts").text
    assert str(originality.UNIQUENESS_THRESHOLD) in body
