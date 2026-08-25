import json

import anthropic
import pytest
from bce.llm import (
    MAX_CLASSIFY_CHARS,
    MAX_CLASSIFY_CHARS_PER_ARTICLE,
    MODEL,
    PROFILE_SCHEMA,
    ProfileClient,
)

VALID = {
    "register": "warm professional",
    "themes": ["mediterranean cruising", "ownership costs"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["berth", "passage", "charter"],
}


class FakeMessages:
    def __init__(self, payload=None, raises=None, stop_reason="end_turn"):
        self.payload = payload
        self.raises = raises
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        if self.stop_reason == "refusal":
            return type("R", (), {"content": [], "stop_reason": "refusal"})()
        block = type("B", (), {"type": "text", "text": json.dumps(self.payload)})()
        return type("R", (), {"content": [block], "stop_reason": "end_turn"})()


class FakeClient:
    def __init__(self, payload=None, raises=None, stop_reason="end_turn"):
        self.messages = FakeMessages(payload, raises, stop_reason)


def test_model_is_opus_5():
    assert MODEL == "claude-opus-5"


def test_schema_names_every_field_we_persist():
    props = PROFILE_SCHEMA["schema"]["properties"]
    assert set(props) == {"register", "themes", "audience_signal", "vocabulary_markers"}


def test_classify_returns_the_parsed_payload():
    got = ProfileClient(client=FakeClient(VALID)).classify(["some article text"])
    assert got == VALID


def test_classify_uses_structured_output_not_the_deprecated_param():
    fake = FakeClient(VALID)
    ProfileClient(client=fake).classify(["text"])
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert "format" in sent["output_config"]
    assert "output_format" not in sent
    assert "budget_tokens" not in json.dumps(sent.get("thinking", {}))


def test_classify_returns_empty_dict_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    assert ProfileClient(client=FakeClient(raises=err)).classify(["text"]) == {}


def test_classify_returns_empty_dict_on_non_dict_payload():
    fake = FakeClient(VALID)
    fake.messages.payload = None  # json.dumps(None) -> "null", parses to None, not a dict
    assert ProfileClient(client=fake).classify(["text"]) == {}


def test_classify_returns_empty_dict_on_unparseable_response():
    fake = FakeClient(VALID)

    def create(**kwargs):
        fake.messages.calls.append(kwargs)
        block = type("B", (), {"type": "text", "text": "not json{"})()
        return type("R", (), {"content": [block], "stop_reason": "end_turn"})()

    fake.messages.create = create
    assert ProfileClient(client=fake).classify(["text"]) == {}


def test_classify_with_no_articles_makes_no_api_call():
    fake = FakeClient(VALID)
    assert ProfileClient(client=fake).classify([]) == {}
    assert fake.messages.calls == []


def test_classify_returns_empty_dict_on_refusal_with_no_text_block():
    # A safety refusal returns HTTP 200 with stop_reason "refusal" and no text
    # content block. Without explicit handling this would still reach json.loads("")
    # and degrade to {} via the JSONDecodeError path, but we assert it explicitly
    # so the behaviour is a deliberate, tested contract rather than an accident.
    fake = FakeClient(stop_reason="refusal")
    assert ProfileClient(client=fake).classify(["text"]) == {}


# --- unbounded corpus: cap what one call sends -------------------------------

def _sent_text(fake):
    return fake.messages.calls[0]["messages"][0]["content"]


def test_classify_caps_each_article():
    fake = FakeClient(VALID)
    ProfileClient(client=fake).classify(["x" * 50_000])
    assert _sent_text(fake).count("x") == MAX_CLASSIFY_CHARS_PER_ARTICLE


def test_classify_caps_the_whole_corpus():
    fake = FakeClient(VALID)
    # 20 articles at the per-article cap would be 80k chars without a total.
    articles = ["y" * 10_000 for _ in range(20)]
    ProfileClient(client=fake).classify(articles)
    # Counted on the corpus itself: the fixed prompt prefix contains a 'y'
    # ("Analyse"), so counting the whole user turn would be off by one.
    assert ProfileClient._bounded_corpus(articles).count("y") == MAX_CLASSIFY_CHARS
    assert len(_sent_text(fake)) < MAX_CLASSIFY_CHARS + 200


def test_classify_leaves_a_normal_corpus_untouched():
    fake = FakeClient(VALID)
    articles = ["Beam matters more than length.", "Draft is the other constraint."]
    ProfileClient(client=fake).classify(articles)
    sent = _sent_text(fake)
    for article in articles:
        assert article in sent


def test_bounded_corpus_never_exceeds_the_total():
    for count, size in [(1, 100_000), (5, 9_000), (50, 500), (3, 10)]:
        got = ProfileClient._bounded_corpus([("z" * size) for _ in range(count)])
        assert got.count("z") <= MAX_CLASSIFY_CHARS
