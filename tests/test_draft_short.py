import anthropic
import pytest
from bce.draft import SHORT_MAX_WORDS, SHORT_MIN_WORDS, DraftClient

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
#: sunreef_relevance. It is deliberately not the kind of fact a model would
#: invent or guess from a headline: it names a made-up refit and gives it a
#: number to two decimal places. If write_short generated its prompt from the
#: angle instead of this body, this string could not appear in the request,
#: because it exists nowhere else.
DISTINCTIVE_CLAIM = "the Solenzara refit brought draft down to 1.34 metres"

LONG_BODY = (
    "Choosing a catamaran for winter charter in the Caribbean means confronting "
    "trade winds most first-time owners underestimate. On the yard side, "
    f"{DISTINCTIVE_CLAIM}, letting owners reach anchorages a deeper hull never "
    "could. That single change reshaped which marinas a boat like this can "
    "actually use in high season."
)


class FakeMessages:
    def __init__(self, text="Headline. Short body.", raises=None, stop_reason="end_turn"):
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
        return type("R", (), {"content": [block], "stop_reason": "end_turn"})()


class FakeClient:
    def __init__(self, text="Headline. Short body.", raises=None, stop_reason="end_turn"):
        self.messages = FakeMessages(text, raises, stop_reason)


def test_write_short_returns_the_condensed_text():
    fake = FakeClient(text="Headline: Winter Charter Draft.\n\nShort body here.")
    got = DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    assert got == "Headline: Winter Charter Draft.\n\nShort body here."


def test_write_short_is_generated_from_the_long_body_not_the_angle():
    """Proves §5's constraint: 'a condensation of the long form, not a
    separate piece'. The distinctive claim above exists only in LONG_BODY --
    an angle (title/premise/audience_value/sunreef_relevance) never carries a
    figure like this. If write_short built its prompt from an angle instead
    of the body, this assertion would fail because the claim would not be in
    the sent request at all.
    """
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert DISTINCTIVE_CLAIM in sent_text


def test_write_short_carries_the_full_long_body():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert LONG_BODY in sent_text


def test_write_short_prompt_states_word_and_headline_requirements():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    system = fake.messages.calls[0]["system"]
    assert "headline" in system.lower()
    assert str(SHORT_MIN_WORDS) in system
    assert str(SHORT_MAX_WORDS) in system


def test_write_short_prompt_forbids_new_claims_and_carries_the_voice():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    system = fake.messages.calls[0]["system"]
    assert "condensation" in system.lower() or "condense" in system.lower()
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "warm professional" in sent_text
    assert "berth" in sent_text


def test_write_short_makes_no_api_call_for_empty_long_body():
    fake = FakeClient()
    assert DraftClient(client=fake).write_short("", PROFILE) is None
    assert DraftClient(client=fake).write_short(None, PROFILE) is None
    assert fake.messages.calls == []


def test_write_short_returns_none_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    got = DraftClient(client=FakeClient(raises=err)).write_short(LONG_BODY, PROFILE)
    assert got is None


def test_write_short_returns_none_on_refusal():
    fake = FakeClient(stop_reason="refusal")
    assert DraftClient(client=fake).write_short(LONG_BODY, PROFILE) is None
