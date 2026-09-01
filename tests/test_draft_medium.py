import anthropic
import pytest
from bce.draft import MAX_TOKENS_MEDIUM, DraftClient

PROFILE = {
    "register": "warm professional",
    "typical_word_count": 850,
    "structure_pattern": {"paragraphs_per_article": 6, "words_per_paragraph": 120},
    "vocabulary_markers": ["berth", "passage", "charter"],
    "sample_quotes": ["Draft is the constraint nobody mentions until it is far too late."],
}

#: The distinctive claim: a specific, oddly precise number tied to an
#: invented shipyard refit, planted ONLY in the long body -- never in an
#: angle, which only ever carries a title/premise/audience_value/
#: sunreef_relevance. Mirrors test_draft_short.py's DISTINCTIVE_CLAIM: if
#: write_medium generated its prompt from the angle instead of the long
#: body, this string could not appear in the request, because it exists
#: nowhere else.
DISTINCTIVE_CLAIM = "the Solenzara refit brought draft down to 1.34 metres"

LONG_BODY = (
    "Choosing a catamaran for winter charter in the Caribbean means confronting "
    "trade winds most first-time owners underestimate. On the yard side, "
    f"{DISTINCTIVE_CLAIM}, letting owners reach anchorages a deeper hull never "
    "could. That single change reshaped which marinas a boat like this can "
    "actually use in high season."
)


class FakeMessages:
    def __init__(self, text="Condensed medium body.", raises=None, stop_reason="end_turn"):
        self.text = text
        self.raises = raises
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        if self.stop_reason == "refusal":
            return type("R", (), {"content": [], "stop_reason": "refusal"})()
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("R", (), {"content": [block], "stop_reason": self.stop_reason})()


class FakeClient:
    def __init__(self, text="Condensed medium body.", raises=None, stop_reason="end_turn"):
        self.messages = FakeMessages(text, raises, stop_reason)


def test_write_medium_returns_the_condensed_text():
    fake = FakeClient(text="A regular-length post condensed from the pillar.")
    got = DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    assert got == "A regular-length post condensed from the pillar."


def test_write_medium_is_generated_from_the_long_body_not_the_angle():
    """Proves §5's constraint for medium, same as write_short: 'a condensation
    of the long form, not a separate piece'. If write_medium built its prompt
    from an angle instead of the body, this assertion would fail -- the claim
    exists nowhere else.
    """
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert DISTINCTIVE_CLAIM in sent_text


def test_write_medium_carries_the_full_long_body():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert LONG_BODY in sent_text


def test_write_medium_targets_the_brokers_typical_word_count():
    """Spec v0.6 §5: the typical_word_count target moved from write_long to
    write_medium -- "matched to their typical_word_count ... the one that has
    to read like them."
    """
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "850" in sent_text


def test_write_medium_prompt_states_voice_match_is_binding():
    """Unlike write_long (encouraged, not binding), write_medium "must
    genuinely read like them" -- the strict/binding voice match belongs here.
    """
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"].lower()
    assert "condens" in system
    assert "warm professional" in fake.messages.calls[0]["messages"][0]["content"]
    assert "berth" in fake.messages.calls[0]["messages"][0]["content"]


def test_write_medium_carries_the_broker_name():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "Acme Yachts" in sent_text


def test_write_medium_makes_no_api_call_for_empty_long_body():
    fake = FakeClient()
    assert DraftClient(client=fake).write_medium("", PROFILE, "Acme Yachts") is None
    assert DraftClient(client=fake).write_medium(None, PROFILE, "Acme Yachts") is None
    assert fake.messages.calls == []


def test_write_medium_returns_none_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    got = DraftClient(client=FakeClient(raises=err)).write_medium(
        LONG_BODY, PROFILE, "Acme Yachts"
    )
    assert got is None


def test_write_medium_returns_none_on_refusal():
    fake = FakeClient(stop_reason="refusal")
    assert DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts") is None


def test_write_medium_returns_none_on_max_tokens_truncation():
    """F2: same treatment as write_long/write_short -- a max_tokens cutoff is
    a failure, not a truncated-but-persisted medium draft.
    """
    fake = FakeClient(text="A regular post that got cut", stop_reason="max_tokens")
    assert DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts") is None


def test_write_medium_prompt_instructs_sunreef_as_one_example_not_the_subject():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"]
    assert "Sunreef" in system
    assert "example" in system.lower()
    assert "not" in system.lower()


def test_write_medium_prompt_forbids_competitor_disparagement():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"]
    for competitor in ("Lagoon", "Fountaine Pajot", "Catana"):
        assert competitor in system


def test_write_medium_uses_opus():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    assert fake.messages.calls[0]["model"] == "claude-opus-5"


def test_max_tokens_medium_is_a_positive_ceiling_distinct_from_long_and_short():
    from bce.draft import MAX_TOKENS_LONG, MAX_TOKENS_SHORT

    assert MAX_TOKENS_MEDIUM > MAX_TOKENS_SHORT
    assert MAX_TOKENS_MEDIUM < MAX_TOKENS_LONG
