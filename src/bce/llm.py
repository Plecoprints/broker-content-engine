"""The judgement half of a voice profile (spec §5 Stage 3).

Register, themes, audience and distinctive vocabulary need reading comprehension,
so they come from one Claude call per broker. The client is injectable so the
suite runs offline and deterministically.
"""
import json

import anthropic

from bce import untrusted

MODEL = "claude-opus-5"
MAX_TOKENS = 2048

#: Ceiling on what one call *sends*. `articles` has a floor and no ceiling, and a
#: long archive page taken through the article fallback can be hundreds of KB, so
#: without this the input cost per call is unbounded while spec §11.5's ceiling
#: counts calls only — and an over-context request raises `APIError`, degrading to
#: `{}` and a statistics-only row that reads as a classifier failure rather than a
#: size problem.
#:
#: 4000 chars is roughly 600-700 words: register, audience, themes and vocabulary
#: are all evident in a piece's opening, and the model sees up to
#: MAX_ARTICLES_PER_BROKER independent samples rather than one long one. The
#: corpus total then bounds a call at ~20k chars (~5k tokens), so the 20-call
#: ceiling now bounds total input as well as call count.
#:
#: Truncation happens *here*, not in `articles`, deliberately: the deterministic
#: statistics must keep the full text. `typical_word_count` is what Stage 4 drafts
#: against (spec §5), so truncating before it is measured would replace an
#: unbounded-cost bug with a wrong-number bug.
MAX_CLASSIFY_CHARS_PER_ARTICLE = 4_000
MAX_CLASSIFY_CHARS = 20_000

#: Spec §10.3 bounds what a broker's page may put into our store. The article
#: text reaching this call is untrusted third-party web content interpolated into
#: the user turn, so these limits are stated in the schema *and* re-applied on
#: persist (`profile.MAX_FIELD_CHARS` / `profile.MAX_LIST_ITEMS`). A schema is a
#: request to the model; the clamp is the enforcement.
MAX_FIELD_CHARS = 120
MAX_LIST_ITEMS = 8

PROFILE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "register": {
                "type": "string",
                "maxLength": MAX_FIELD_CHARS,
                "description": "Formality and tone in a few words, e.g. 'warm professional'",
            },
            "themes": {
                "type": "array",
                "maxItems": MAX_LIST_ITEMS,
                "items": {"type": "string", "maxLength": MAX_FIELD_CHARS},
                "description": "Recurring subjects, 3-6 short phrases",
            },
            "audience_signal": {
                "type": "string",
                "maxLength": MAX_FIELD_CHARS,
                "description": "Who they are writing for: charter clients, owners, investors",
            },
            "vocabulary_markers": {
                "type": "array",
                "maxItems": MAX_LIST_ITEMS,
                "items": {"type": "string", "maxLength": MAX_FIELD_CHARS},
                "description": "Distinctive words this writer reaches for",
            },
        },
        "required": ["register", "themes", "audience_signal", "vocabulary_markers"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You analyse how a yacht brokerage writes, so their voice can be matched. "
    "Report only what the text supports. Do not invent themes that are not present."
)


class ProfileClient:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    @staticmethod
    def _bounded_corpus(articles: list[str]) -> str:
        """The corpus as one turn, capped per article and in total."""
        kept: list[str] = []
        budget = MAX_CLASSIFY_CHARS
        for article in articles:
            if budget <= 0:
                break
            piece = article[:min(MAX_CLASSIFY_CHARS_PER_ARTICLE, budget)]
            kept.append(piece)
            budget -= len(piece)
        return "\n\n---\n\n".join(kept)

    def classify(self, articles: list[str]) -> dict:
        if not articles:
            return {}
        joined = self._bounded_corpus(articles)
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM + untrusted.INSTRUCTION,
                output_config={"format": PROFILE_SCHEMA, "effort": "medium"},
                messages=[
                    {
                        "role": "user",
                        "content": (
                            "Analyse the voice of these articles:\n\n"
                            + untrusted.fence(joined, "broker articles")
                        ),
                    }
                ],
            )
        except anthropic.APIError:
            return {}
        # A safety refusal returns HTTP 200 with stop_reason "refusal" and
        # ordinarily no text content block. That already degrades to {} below
        # (no text -> "" -> json.JSONDecodeError), but we check explicitly so
        # the refusal path is a deliberate, tested contract rather than an
        # accident of empty-string parsing.
        if response.stop_reason == "refusal":
            return {}
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
