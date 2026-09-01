import json

import anthropic
import pytest
from bce.angles import (
    ANGLE_SCHEMA,
    MAX_ANGLES,
    MAX_AUDIENCE_VALUE_CHARS,
    MAX_PREMISE_CHARS,
    MAX_SUNREEF_RELEVANCE_CHARS,
    MAX_TITLE_CHARS,
    MIN_ANGLES,
    MODEL,
    AngleClient,
    best_angle,
)

PROFILE = {
    "register": "warm professional",
    "themes": ["mediterranean cruising", "ownership costs"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["berth", "passage", "charter"],
}


def _angle(title="Title", score=0.5):
    return {
        "title": title,
        "premise": "A premise.",
        "audience_value": "Helps owners decide.",
        "sunreef_relevance": "Mentions catamaran ownership in passing.",
        "score": score,
    }


VALID = {"angles": [_angle("A", 0.4), _angle("B", 0.9), _angle("C", 0.2)]}


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
    props = ANGLE_SCHEMA["schema"]["properties"]["angles"]["items"]["properties"]
    assert set(props) == {
        "title",
        "premise",
        "audience_value",
        "sunreef_relevance",
        "score",
    }


def test_schema_bounds_list_length():
    angles_schema = ANGLE_SCHEMA["schema"]["properties"]["angles"]
    assert angles_schema["minItems"] == MIN_ANGLES
    assert angles_schema["maxItems"] == MAX_ANGLES


def test_propose_returns_the_parsed_angles():
    got = AngleClient(client=FakeClient(VALID)).propose(PROFILE, "Acme Yachts")
    assert [a["title"] for a in got] == ["A", "B", "C"]
    assert got[1]["score"] == 0.9


def test_propose_uses_structured_output_not_the_deprecated_param():
    fake = FakeClient(VALID)
    AngleClient(client=fake).propose(PROFILE, "Acme Yachts")
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert "format" in sent["output_config"]
    assert "output_format" not in sent
    assert "budget_tokens" not in json.dumps(sent.get("thinking", {}))


def test_propose_carries_the_voice_profile_in_the_prompt():
    fake = FakeClient(VALID)
    AngleClient(client=fake).propose(PROFILE, "Acme Yachts")
    sent_text = fake.messages.calls[0]["messages"][0]["content"]
    assert "Acme Yachts" in sent_text
    assert "warm professional" in sent_text
    assert "mediterranean cruising" in sent_text
    assert "prospective owners" in sent_text
    assert "berth" in sent_text


def test_propose_prompt_forbids_competitor_disparagement():
    """F7: angles are persisted and shown to the operator regardless of
    whether a draft is ever written, so the competitor ban (spec §2) must
    reach the angle-proposal prompt too, not just draft.py's long/short
    system prompts.
    """
    fake = FakeClient(VALID)
    AngleClient(client=fake).propose(PROFILE, "Acme Yachts")
    system = fake.messages.calls[0]["system"]
    for competitor in ("Lagoon", "Fountaine Pajot", "Catana"):
        assert competitor in system


def test_propose_makes_no_api_call_for_empty_profile():
    fake = FakeClient(VALID)
    assert AngleClient(client=fake).propose({}, "Acme Yachts") == []
    assert fake.messages.calls == []


def test_propose_returns_empty_list_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    got = AngleClient(client=FakeClient(raises=err)).propose(PROFILE, "Acme Yachts")
    assert got == []


def test_propose_returns_empty_list_on_refusal():
    fake = FakeClient(stop_reason="refusal")
    assert AngleClient(client=fake).propose(PROFILE, "Acme Yachts") == []


def test_propose_returns_empty_list_on_unparseable_response():
    fake = FakeClient(VALID)

    def create(**kwargs):
        fake.messages.calls.append(kwargs)
        block = type("B", (), {"type": "text", "text": "not json{"})()
        return type("R", (), {"content": [block], "stop_reason": "end_turn"})()

    fake.messages.create = create
    assert AngleClient(client=fake).propose(PROFILE, "Acme Yachts") == []


def test_propose_returns_empty_list_when_payload_is_not_a_dict():
    fake = FakeClient(None)  # json.dumps(None) -> "null" -> parses to None
    assert AngleClient(client=fake).propose(PROFILE, "Acme Yachts") == []


def test_propose_returns_empty_list_when_angles_key_is_not_a_list():
    fake = FakeClient({"angles": "not a list"})
    assert AngleClient(client=fake).propose(PROFILE, "Acme Yachts") == []


def test_propose_drops_malformed_entries_but_keeps_the_rest():
    payload = {"angles": [_angle("Good", 0.5), "not a dict", {"premise": "no title"}]}
    got = AngleClient(client=FakeClient(payload)).propose(PROFILE, "Acme Yachts")
    assert [a["title"] for a in got] == ["Good"]


def test_propose_clamps_an_over_long_title():
    over_long = _angle(title="x" * (MAX_TITLE_CHARS + 500), score=0.5)
    got = AngleClient(client=FakeClient({"angles": [over_long]})).propose(
        PROFILE, "Acme Yachts"
    )
    assert len(got[0]["title"]) == MAX_TITLE_CHARS


def test_propose_clamps_over_long_premise_audience_value_and_sunreef_relevance():
    angle = _angle(title="Fine", score=0.5)
    angle["premise"] = "p" * (MAX_PREMISE_CHARS + 200)
    angle["audience_value"] = "a" * (MAX_AUDIENCE_VALUE_CHARS + 200)
    angle["sunreef_relevance"] = "s" * (MAX_SUNREEF_RELEVANCE_CHARS + 200)
    got = AngleClient(client=FakeClient({"angles": [angle]})).propose(
        PROFILE, "Acme Yachts"
    )
    assert len(got[0]["premise"]) == MAX_PREMISE_CHARS
    assert len(got[0]["audience_value"]) == MAX_AUDIENCE_VALUE_CHARS
    assert len(got[0]["sunreef_relevance"]) == MAX_SUNREEF_RELEVANCE_CHARS


def test_propose_clamps_score_into_zero_one_range():
    too_high = _angle("High", score=5.0)
    too_low = _angle("Low", score=-3.0)
    not_a_number = _angle("Bad", score="not-a-number")
    got = AngleClient(client=FakeClient({"angles": [too_high, too_low, not_a_number]})).propose(
        PROFILE, "Acme Yachts"
    )
    scores = {a["title"]: a["score"] for a in got}
    assert scores["High"] == 1.0
    assert scores["Low"] == 0.0
    assert scores["Bad"] == 0.0


def test_propose_truncates_a_response_with_too_many_angles():
    payload = {"angles": [_angle(f"T{i}", 0.1 * i) for i in range(10)]}
    got = AngleClient(client=FakeClient(payload)).propose(PROFILE, "Acme Yachts")
    assert len(got) == MAX_ANGLES


def test_keyword_source_defaults_to_none_and_is_not_called():
    client = AngleClient(client=FakeClient(VALID))
    assert client.propose(PROFILE, "Acme Yachts") is not None
    # keyword_source stays a documented, unwired seam for this task.
    assert AngleClient().keyword_source is None


def test_best_angle_picks_the_highest_score():
    angles = [_angle("A", 0.4), _angle("B", 0.9), _angle("C", 0.2)]
    assert best_angle(angles)["title"] == "B"


def test_best_angle_returns_none_for_empty_list():
    assert best_angle([]) is None
