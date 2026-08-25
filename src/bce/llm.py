"""The judgement half of a voice profile (spec §5 Stage 3).

Register, themes, audience and distinctive vocabulary need reading comprehension,
so they come from one Claude call per broker. The client is injectable so the
suite runs offline and deterministically.
"""
import json

import anthropic

MODEL = "claude-opus-5"
MAX_TOKENS = 2048

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

    def classify(self, articles: list[str]) -> dict:
        if not articles:
            return {}
        joined = "\n\n---\n\n".join(articles)
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM,
                output_config={"format": PROFILE_SCHEMA, "effort": "medium"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Analyse the voice of these articles:\n\n{joined}",
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
