"""Long-form drafting (spec §5 Stage 4, spec §2, §3).

Shares the failure contract of `bce.angles.AngleClient` and
`bce.llm.ProfileClient`: the client is injectable and lazily constructed so no
test needs an API key, and every failure -- `anthropic.APIError`, a safety
refusal, or a response with no usable text -- degrades to `None`, never
raises.

Unlike `angles.propose` / `llm.classify`, the payload here is prose (an
article body), not a value we persist as structured columns, so there is no
`output_config` JSON schema and no clamp step; the failure-handling shape is
the only thing carried over from that pattern.
"""
import anthropic

MODEL = "claude-opus-5"

#: Long-form is a full article matched to the broker's own typical_word_count
#: (spec §5). Sized generously above it (~1.5 tokens/word plus overhead for
#: instructions) rather than tied to a specific broker's word count, since
#: max_tokens bounds the call, not the target length.
MAX_TOKENS_LONG = 4096

#: Spec §2: "Content never positions against Lagoon, Fountaine Pajot, Catana,
#: or others by name." Named explicitly in the system prompt (not just
#: described abstractly as "competitors") so the model has the actual names
#: it must not use against the broker's own brand.
COMPETITORS = ("Lagoon", "Fountaine Pajot", "Catana")

_LONG_SYSTEM = (
    "You draft long-form editorial content for a yacht brokerage's own blog "
    "or journal, written in that broker's own voice. Match the register, "
    "structure, and vocabulary described in the voice profile below, and "
    "target the given word count -- it is this broker's own typical article "
    "length, not a generic default.\n\n"
    "If Sunreef is genuinely relevant to the angle, it may appear as one "
    "example among several -- never as the subject of the piece, and never "
    "written as an advertisement for Sunreef.\n\n"
    "Never disparage or position against named competitors -- "
    f"{', '.join(COMPETITORS)} are never named or argued against, regardless "
    "of how relevant the comparison might seem."
)


def _structure_summary(structure_pattern) -> str | None:
    """`profile['structure_pattern']` as one line of prose, or None.

    Expects the already-parsed shape `style.structure_pattern` describes --
    `{"paragraphs_per_article": .., "words_per_paragraph": ..}` -- the same
    already-deserialised profile dict `angles.AngleClient.propose` takes,
    since that deserialisation is the caller's job, not this module's.
    """
    if not isinstance(structure_pattern, dict):
        return None
    paragraphs = structure_pattern.get("paragraphs_per_article")
    words = structure_pattern.get("words_per_paragraph")
    if paragraphs is None and words is None:
        return None
    parts = []
    if paragraphs is not None:
        parts.append(f"about {paragraphs} paragraphs")
    if words is not None:
        parts.append(f"about {words} words per paragraph")
    return "Typical structure: " + ", ".join(parts) + "."


def _profile_summary(profile: dict) -> str:
    """The voice profile as prose, so the draft matches this broker's voice."""
    if not isinstance(profile, dict):
        return ""
    lines = []
    if register := profile.get("register"):
        lines.append(f"Register: {register}")
    if word_count := profile.get("typical_word_count"):
        lines.append(
            f"Target length: about {word_count} words "
            "(this broker's own typical article length)."
        )
    if structure_line := _structure_summary(profile.get("structure_pattern")):
        lines.append(structure_line)
    vocabulary_markers = profile.get("vocabulary_markers")
    if isinstance(vocabulary_markers, list) and vocabulary_markers:
        lines.append(
            "Distinctive vocabulary: " + ", ".join(str(v) for v in vocabulary_markers)
        )
    sample_quotes = profile.get("sample_quotes")
    if isinstance(sample_quotes, list) and sample_quotes:
        lines.append("Sample quotes in this broker's voice:")
        lines.extend(f"- {quote}" for quote in sample_quotes)
    return "\n".join(lines)


def _angle_summary(angle: dict) -> str:
    return (
        f"Title: {angle.get('title', '')}\n"
        f"Premise: {angle.get('premise', '')}\n"
        f"Audience value: {angle.get('audience_value', '')}\n"
        f"Sunreef relevance: {angle.get('sunreef_relevance', '')}"
    )


def _extract_text(response) -> str:
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text.strip()


class DraftClient:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _create(self, *, system: str, user_content: str, max_tokens: int) -> str | None:
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APIError:
            return None
        # A safety refusal is HTTP 200 with stop_reason "refusal" and
        # ordinarily no text content block -- see AngleClient.propose /
        # ProfileClient.classify for the same, explicitly-tested contract.
        if response.stop_reason == "refusal":
            return None
        text = _extract_text(response)
        return text or None

    def write_long(self, angle: dict, profile: dict, broker_name: str) -> str | None:
        """A full article in the broker's voice, or None on any failure.

        No call is made without an angle: there is nothing to draft against.
        """
        if not angle:
            return None
        user_content = (
            f"Broker: {broker_name}\n\n"
            f"Angle:\n{_angle_summary(angle)}\n\n"
            f"Voice profile:\n{_profile_summary(profile)}"
        )
        return self._create(
            system=_LONG_SYSTEM, user_content=user_content, max_tokens=MAX_TOKENS_LONG
        )
