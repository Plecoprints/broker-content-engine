"""Angle generation (spec §5 Stage 4, spec §3): decide what a broker should write.

A broker publishes what helps them sell yachts and serve clients, not a Sunreef
advertisement. `audience_value` exists precisely so an angle that cannot answer
"why would this broker publish this?" is visibly not a candidate — the model is
asked for it, and nothing downstream should treat an angle missing it as fully
formed. This mirrors `bce.llm.ProfileClient`: same client-injection shape, same
degrade-to-empty-on-any-failure contract, same schema-requests/clamp-enforces
split.
"""
import json

import anthropic

from bce.draft import COMPETITORS

MODEL = "claude-opus-5"
MAX_TOKENS = 2048

#: How many angles we ask for, and the hard ceiling enforced on the way out.
#: A broker needs a real choice (spec §3) but the operator reviewing them
#: should not have to wade through more than a handful.
MIN_ANGLES = 3
MAX_ANGLES = 5

#: Field bounds, sized to what each field actually holds rather than reusing
#: one constant for everything: `title` is a headline, `premise` is a short
#: paragraph, `audience_value` / `sunreef_relevance` are one-sentence
#: justifications. As with `llm.PROFILE_SCHEMA`, these are stated in the
#: schema *and* re-applied as a clamp on parse: the schema is a request to the
#: model, the clamp is the enforcement (the model's output is untrusted, and a
#: `maxLength` in a JSON schema is not a guarantee).
MAX_TITLE_CHARS = 120
MAX_PREMISE_CHARS = 500
MAX_AUDIENCE_VALUE_CHARS = 300
MAX_SUNREEF_RELEVANCE_CHARS = 300

ANGLE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "angles": {
                "type": "array",
                "minItems": MIN_ANGLES,
                "maxItems": MAX_ANGLES,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {
                            "type": "string",
                            "maxLength": MAX_TITLE_CHARS,
                            "description": "A headline for the article",
                        },
                        "premise": {
                            "type": "string",
                            "maxLength": MAX_PREMISE_CHARS,
                            "description": "What the article argues or covers",
                        },
                        "audience_value": {
                            "type": "string",
                            "maxLength": MAX_AUDIENCE_VALUE_CHARS,
                            "description": (
                                "Why THIS broker's readers (owners, charter "
                                "clients, prospects) would want to read this"
                            ),
                        },
                        "sunreef_relevance": {
                            "type": "string",
                            "maxLength": MAX_SUNREEF_RELEVANCE_CHARS,
                            "description": (
                                "How this connects to catamaran ownership/"
                                "brokerage without reading as an advertisement"
                            ),
                        },
                        "score": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                            "description": "How compelling and publishable, 0-1",
                        },
                    },
                    "required": [
                        "title",
                        "premise",
                        "audience_value",
                        "sunreef_relevance",
                        "score",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["angles"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You propose article angles for a yacht brokerage's own editorial content. "
    "Each angle must be something this specific broker would plausibly publish "
    "to help sell yachts and serve their clients — not an advertisement for any "
    "yacht brand. Never propose an angle that disparages or positions against "
    f"named competitors -- {', '.join(COMPETITORS)} are never named or argued "
    "against in an angle, regardless of how relevant the comparison might "
    "seem. Calibrate to the voice profile given: its register, themes, "
    "audience, and vocabulary. Score each angle 0-1 on how compelling and "
    "publishable it is for this broker's actual readers."
)


def _profile_summary(profile: dict) -> str:
    """The voice profile as prose, so the angles suit this broker's readers."""
    lines = []
    if register := profile.get("register"):
        lines.append(f"Register: {register}")
    if audience_signal := profile.get("audience_signal"):
        lines.append(f"Audience: {audience_signal}")
    themes = profile.get("themes")
    if isinstance(themes, list) and themes:
        lines.append("Recurring themes: " + ", ".join(str(t) for t in themes))
    vocabulary_markers = profile.get("vocabulary_markers")
    if isinstance(vocabulary_markers, list) and vocabulary_markers:
        lines.append(
            "Distinctive vocabulary: " + ", ".join(str(v) for v in vocabulary_markers)
        )
    return "\n".join(lines)


def _clamp_field(value, max_chars: int) -> str:
    """A bounded string, or '' when the model returned nothing usable."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_chars]


def _clamp_score(value) -> float:
    """A float in [0, 1], or 0.0 when the model returned nothing numeric."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, min(1.0, float(value)))


def _clamp_angle(raw) -> dict | None:
    """One angle, bounded to the persisted shape, or None if unusable.

    A missing title makes the whole entry unusable — every other field is
    (deliberately) allowed to clamp down to an empty string rather than drop
    the angle, but a title-less angle is not a candidate at all.
    """
    if not isinstance(raw, dict):
        return None
    title = _clamp_field(raw.get("title"), MAX_TITLE_CHARS)
    if not title:
        return None
    return {
        "title": title,
        "premise": _clamp_field(raw.get("premise"), MAX_PREMISE_CHARS),
        "audience_value": _clamp_field(raw.get("audience_value"), MAX_AUDIENCE_VALUE_CHARS),
        "sunreef_relevance": _clamp_field(
            raw.get("sunreef_relevance"), MAX_SUNREEF_RELEVANCE_CHARS
        ),
        "score": _clamp_score(raw.get("score")),
    }


class AngleClient:
    def __init__(self, client=None, keyword_source=None):
        self._client = client
        #: Seam for Semrush keyword research (not wired in this task). Once
        #: wired, this would be an object with something like
        #: `search(broker_name: str, themes: list[str]) -> list[dict]`, whose
        #: results get folded into the prompt so angles reflect what this
        #: broker's audience actually searches for. Left None because the
        #: live Semrush response shape has not been verified — building
        #: against an unverified shape is how a real defect shipped earlier
        #: in this project (spec §3 follow-up).
        self.keyword_source = keyword_source

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def propose(self, profile: dict, broker_name: str) -> list[dict]:
        if not profile:
            return []
        summary = _profile_summary(profile)
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM,
                output_config={"format": ANGLE_SCHEMA, "effort": "medium"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Broker: {broker_name}\n\n{summary}",
                    }
                ],
            )
        except anthropic.APIError:
            return []
        # See ProfileClient.classify: a safety refusal is HTTP 200 with
        # stop_reason "refusal" and ordinarily no text block, which already
        # degrades to [] below via json.JSONDecodeError -- checked explicitly
        # so it is a deliberate, tested contract rather than an accident.
        if response.stop_reason == "refusal":
            return []
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, dict):
            return []
        raw_angles = parsed.get("angles")
        if not isinstance(raw_angles, list):
            return []
        angles = []
        for raw in raw_angles[:MAX_ANGLES]:
            clamped = _clamp_angle(raw)
            if clamped is not None:
                angles.append(clamped)
        return angles


def best_angle(angles: list[dict]) -> dict | None:
    """The highest-scoring angle, or None for an empty list."""
    if not angles:
        return None
    return max(angles, key=lambda a: a.get("score") or 0.0)
