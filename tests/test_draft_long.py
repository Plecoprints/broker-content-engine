import json

import anthropic
import pytest
from bce.draft import LONG_MAX_WORDS, LONG_MIN_WORDS, MAX_TOKENS_LONG, MODEL, DraftClient

ANGLE = {
    "title": "Provisioning for a Two-Week Mediterranean Crossing",
    "premise": "What owners actually pack, versus what the checklists say.",
    "audience_value": "Helps prospective owners plan a realistic first passage.",
    "sunreef_relevance": "Mentions catamaran galley storage in passing.",
}

PROFILE = {
    "register": "warm professional",
    "typical_word_count": 850,
    "structure_pattern": {"paragraphs_per_article": 6, "words_per_paragraph": 120},
    "vocabulary_markers": ["berth", "passage", "charter"],
    "sample_quotes": ["Draft is the constraint nobody mentions until it is far too late."],
}


class FakeMessages:
    def __init__(self, text="Draft body.", raises=None, stop_reason="end_turn"):
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
        # A max_tokens cutoff still carries a (truncated) text block -- it is
        # only the refusal case that ordinarily has none. Pass stop_reason
        # through rather than hardcoding "end_turn" so tests can exercise it.
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("R", (), {"content": [block], "stop_reason": self.stop_reason})()


class FakeClient:
    def __init__(self, text="Draft body.", raises=None, stop_reason="end_turn"):
        self.messages = FakeMessages(text, raises, stop_reason)


def test_model_is_opus_5():
    assert MODEL == "claude-opus-5"


def test_write_long_returns_the_drafted_text():
    fake = FakeClient(text="Full article body about provisioning.")
    got = DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    assert got == "Full article body about provisioning."


def test_write_long_uses_opus_and_no_deprecated_params():
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert "output_format" not in sent
    assert "budget_tokens" not in json.dumps(sent.get("thinking", {}))


def test_long_is_now_the_pillar_length_2000_to_2300_words():
    """Spec v0.6 §5: long moved from "match typical_word_count" to a fixed
    2000-2300 word pillar target -- that word-count target moved to
    write_medium (see test_draft_medium.py)."""
    assert LONG_MIN_WORDS == 2000
    assert LONG_MAX_WORDS == 2300


def test_write_long_carries_the_pillar_length_target_not_typical_word_count():
    """The semantics shift, asserted directly: write_long's target is now the
    fixed pillar range, not this broker's own typical_word_count (850 in
    PROFILE) -- that number belongs to write_medium now, not write_long.
    """
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert str(LONG_MIN_WORDS) in sent_text
    assert str(LONG_MAX_WORDS) in sent_text
    assert "850" not in sent_text


def test_write_long_prompt_says_voice_matching_is_encouraged_not_binding():
    """Spec v0.6 §5: "Voice matching is encouraged but not binding" at pillar
    length -- no broker's typical_word_count is anywhere near 2000-2300 words,
    so the system prompt must say this is different from the strict voice
    match write_medium performs.
    """
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"].lower()
    assert "encourag" in system
    assert "not binding" in system or "not required" in system


def test_max_tokens_long_is_sized_for_the_pillar_target():
    """~1.5 tokens/word * 2300 words is already ~3450 tokens; MAX_TOKENS_LONG
    must clear that with real headroom for structure/headline overhead, not
    just barely exceed the raw word-count arithmetic.
    """
    assert MAX_TOKENS_LONG >= 5000


def test_write_long_carries_the_angle_and_broker_name():
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "Acme Yachts" in sent_text
    assert "Provisioning for a Two-Week Mediterranean Crossing" in sent_text
    assert "warm professional" in sent_text
    assert "berth" in sent_text


def test_write_long_prompt_instructs_sunreef_as_one_example_not_the_subject():
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"]
    assert "Sunreef" in system
    assert "example" in system.lower()
    assert "not" in system.lower()


def test_write_long_prompt_forbids_competitor_disparagement():
    fake = FakeClient(text="Body.")
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"]
    for competitor in ("Lagoon", "Fountaine Pajot", "Catana"):
        assert competitor in system


def test_write_long_makes_no_api_call_without_an_angle():
    fake = FakeClient(text="Body.")
    assert DraftClient(client=fake).write_long({}, PROFILE, "Acme Yachts") is None
    assert DraftClient(client=fake).write_long(None, PROFILE, "Acme Yachts") is None
    assert fake.messages.calls == []


def test_write_long_returns_none_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    got = DraftClient(client=FakeClient(raises=err)).write_long(ANGLE, PROFILE, "Acme Yachts")
    assert got is None


def test_write_long_returns_none_on_refusal():
    fake = FakeClient(stop_reason="refusal")
    assert DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts") is None


def test_write_long_returns_none_on_max_tokens_truncation():
    """F2: a stop_reason of 'max_tokens' must be treated as failure, not a
    successful (but silently truncated) draft -- even though the response
    still carries a text block, unlike a refusal.
    """
    fake = FakeClient(text="Choosing a catamaran means conf", stop_reason="max_tokens")
    assert DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts") is None
