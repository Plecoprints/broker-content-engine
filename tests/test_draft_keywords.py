"""Keyword guidance in the drafting prompt (spec §5b): "The selected keywords
go into the prompt as terms to work in naturally... must read naturally and
must not be stuffed... the primary should appear in the title or first
paragraph where it fits."

Fixtures are built inline (the shape `bce.keywords.select_for_draft`
returns), not via the database or `bce.seed` -- this file only tests the
prompt-construction contract, not selection itself (see test_keywords.py).
"""
from bce.draft import DraftClient

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
    "sample_quotes": [],
}

LONG_BODY = "Choosing a catamaran for winter charter means confronting trade winds."

KEYWORDS = {
    "primary": {"id": 1, "phrase": "catamaran for sale", "volume": 8100, "difficulty": 25},
    "secondary": [
        {"id": 2, "phrase": "catamarans for sale", "volume": 4400, "difficulty": 24},
        {"id": 3, "phrase": "what is a catamaran", "volume": 1900, "difficulty": 25},
    ],
}

EMPTY_SELECTION = {"primary": None, "secondary": []}


class FakeMessages:
    def __init__(self, text="Draft body.", stop_reason="end_turn"):
        self.text = text
        self.stop_reason = stop_reason
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        block = type("B", (), {"type": "text", "text": self.text})()
        return type("R", (), {"content": [block], "stop_reason": self.stop_reason})()


class FakeClient:
    def __init__(self, text="Draft body."):
        self.messages = FakeMessages(text)


def _sent_user_content(fake):
    return fake.messages.calls[0]["messages"][0]["content"]


def _sent_system(fake):
    return fake.messages.calls[0]["system"]


# --- write_long ----------------------------------------------------------


def test_write_long_carries_primary_and_secondary_keywords_when_given():
    fake = FakeClient()
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts", keywords=KEYWORDS)
    content = _sent_user_content(fake)
    assert "catamaran for sale" in content
    assert "catamarans for sale" in content
    assert "what is a catamaran" in content


def test_write_long_without_keywords_arg_is_unaffected():
    """Backward compatibility: omitting `keywords` entirely must produce the
    exact same call shape as before this task (existing callers, existing
    tests, are untouched).
    """
    fake = FakeClient()
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts")
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


def test_write_long_with_empty_selection_adds_no_keyword_guidance():
    """spec §5b: 'If nothing qualifies... the draft is still written' -- an
    empty selection (primary=None) must degrade exactly like keywords=None,
    not render a guidance block with nothing in it.
    """
    fake = FakeClient()
    DraftClient(client=fake).write_long(
        ANGLE, PROFILE, "Acme Yachts", keywords=EMPTY_SELECTION
    )
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


def test_write_long_system_prompt_says_read_naturally_and_not_stuffed():
    fake = FakeClient()
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts", keywords=KEYWORDS)
    system = _sent_system(fake).lower()
    assert "natural" in system
    assert "stuff" in system


def test_write_long_system_prompt_places_primary_in_title_or_first_paragraph():
    fake = FakeClient()
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts", keywords=KEYWORDS)
    system = _sent_system(fake).lower()
    assert "title" in system
    assert "first paragraph" in system


def test_write_long_user_content_marks_the_primary_keyword_distinctly():
    fake = FakeClient()
    DraftClient(client=fake).write_long(ANGLE, PROFILE, "Acme Yachts", keywords=KEYWORDS)
    content = _sent_user_content(fake)
    assert "Primary" in content
    assert "Secondary" in content


# --- write_medium ----------------------------------------------------------


def test_write_medium_carries_keywords_when_given():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(
        LONG_BODY, PROFILE, "Acme Yachts", keywords=KEYWORDS
    )
    content = _sent_user_content(fake)
    assert "catamaran for sale" in content
    assert "catamarans for sale" in content


def test_write_medium_without_keywords_arg_is_unaffected():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(LONG_BODY, PROFILE, "Acme Yachts")
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


def test_write_medium_with_empty_selection_adds_no_guidance():
    fake = FakeClient()
    DraftClient(client=fake).write_medium(
        LONG_BODY, PROFILE, "Acme Yachts", keywords=EMPTY_SELECTION
    )
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


# --- write_short -------------------------------------------------------------


def test_write_short_carries_primary_keyword_when_given():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE, keywords=KEYWORDS)
    content = _sent_user_content(fake)
    assert "catamaran for sale" in content


def test_write_short_without_keywords_arg_is_unaffected():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE)
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


def test_write_short_with_empty_selection_adds_no_guidance():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE, keywords=EMPTY_SELECTION)
    content = _sent_user_content(fake)
    assert "Keywords to work in" not in content


def test_write_short_system_prompt_says_read_naturally_and_not_stuffed():
    fake = FakeClient()
    DraftClient(client=fake).write_short(LONG_BODY, PROFILE, keywords=KEYWORDS)
    system = _sent_system(fake).lower()
    assert "natural" in system
    assert "stuff" in system
