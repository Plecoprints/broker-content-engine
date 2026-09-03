"""Long-, medium-, and short-form drafting (spec §5 Stage 4/5, spec §2, §3).

Three calls, sharing the failure contract of `bce.angles.AngleClient` and
`bce.llm.ProfileClient`: the client is injectable and lazily constructed so no
test needs an API key, and every failure -- `anthropic.APIError`, a safety
refusal, a `max_tokens` truncation, or a response with no usable text --
degrades to `None`, never raises.

`max_tokens` truncation is treated as failure, not success, and this module is
the one place that distinction actually matters. `ProfileClient` and
`AngleClient` request structured JSON output; a truncated response there is
simply unparseable JSON and already degrades to empty via the existing
parse-failure path. `DraftClient` requests prose, so a response cut off mid-
article is syntactically fine text -- indistinguishable from a deliberately
short article unless `stop_reason` is checked explicitly. Persisting a
truncated draft as `pending_review`, and then condensing medium/short from
that same truncated text, would ship three wrong rows from one silent
failure.

Unlike `angles.propose` / `llm.classify`, the payload here is prose (an
article body, a blog post, a newsletter blurb), not a value we persist as
structured columns, so there is no `output_config` JSON schema and no clamp
step; the failure-handling shape is the only thing carried over from that
pattern.

**Spec v0.6 §5 changed what `long` targets.** It used to be a full article
matched to the broker's own `typical_word_count`; it is now a 2000-2300 word
*pillar* piece, comprehensive by design, where voice matching is encouraged
but not binding -- no broker's own typical article is anywhere near that
length. The `typical_word_count` target moved to `write_medium`, which is the
format that "has to read like them" (spec §5): matched to this broker's own
typical length, voice-matched strictly, sitting alongside their own posts.

`write_medium` and `write_short` both take the long draft's BODY, not the
angle, because spec §5 is explicit that both are "condensations of the long
form, not independent generations (same angle, same claims)" -- generating
each independently against the angle would drift, and a broker who sees more
than one format would read them as incoherent with each other.
"""
import anthropic

from bce import untrusted

MODEL = "claude-opus-5"

#: Spec §5: the pillar (`long`) target is a fixed 2000-2300 words, not this
#: broker's own typical_word_count -- see the module docstring.
LONG_MIN_WORDS = 2000
LONG_MAX_WORDS = 2300

#: Spec §5: the short form is "headline, 100-200 words".
SHORT_MIN_WORDS = 100
SHORT_MAX_WORDS = 200

#: Token ceilings, sized generously above each format's target (roughly 1.5
#: tokens/word plus overhead for headline/instructions) rather than tied to a
#: specific broker's word count, since max_tokens bounds the call, not the
#: target length itself.
#:
#: MAX_TOKENS_LONG: at 2300 words, 1.5 tokens/word alone is already ~3450
#: tokens -- the old value (4096, sized for a broker's typical_word_count,
#: which is rarely more than ~1000 words) had almost no headroom left over
#: for a pillar-length article. Raised to 6144 (1.5x the old ceiling): enough
#: for ~4000 words at 1.5 tokens/word, comfortable headroom above the 2300-
#: word target plus paragraph breaks and a heading.
MAX_TOKENS_LONG = 6144
#: MAX_TOKENS_MEDIUM: this is what MAX_TOKENS_LONG used to size for --
#: matched to a broker's own typical_word_count. Carried over unchanged now
#: that write_medium is the format that target actually applies to.
MAX_TOKENS_MEDIUM = 4096
MAX_TOKENS_SHORT = 768

#: Spec §2: "Content never positions against Lagoon, Fountaine Pajot, Catana,
#: or others by name." Named explicitly in the system prompt (not just
#: described abstractly as "competitors") so the model has the actual names
#: it must not use against the broker's own brand.
COMPETITORS = ("Lagoon", "Fountaine Pajot", "Catana")

#: Spec §5b: keywords go into the prompt as terms to work in, not a checklist
#: to satisfy -- appended to every format's system prompt (static, present
#: whether or not a given call actually carries keyword guidance) so the
#: constraint holds even if a future caller forgets the reminder in the user
#: turn. `_keyword_guidance` below is the per-call, data-carrying half: the
#: actual selected phrases, only added when there is something to add.
_KEYWORD_INSTRUCTION = (
    "If keyword guidance is given below, work every keyword in naturally -- "
    "as ordinary language a reader would not notice was chosen for search "
    "intent -- and never stuff them in mechanically. The primary keyword "
    "should appear in the title or the first paragraph, wherever it fits "
    "naturally, not forced."
)

_LONG_SYSTEM = (
    "You draft a long-form PILLAR article for a yacht brokerage's own blog or "
    "journal -- a comprehensive, cornerstone piece on the topic, not a "
    f"regular post. Target {LONG_MIN_WORDS}-{LONG_MAX_WORDS} words: at this "
    "length the piece must serve depth and comprehensive coverage first.\n\n"
    "Voice matching against the register, structure, and vocabulary "
    "described in the voice profile below is encouraged, and should be "
    "applied as far as it reasonably goes -- but it is not binding at this "
    "length. No broker's own typical article is anywhere near 2000-2300 "
    "words, so this piece is a different product from their regular posts, "
    "not simply a longer version of one; comprehensive coverage of the topic "
    "takes priority over matching their register exactly.\n\n"
    "If Sunreef is genuinely relevant to the angle, it may appear as one "
    "example among several -- never as the subject of the piece, and never "
    "written as an advertisement for Sunreef.\n\n"
    "Never disparage or position against named competitors -- "
    f"{', '.join(COMPETITORS)} are never named or argued against, regardless "
    "of how relevant the comparison might seem."
    + "\n\n" + _KEYWORD_INSTRUCTION
)

_MEDIUM_SYSTEM = (
    "You condense a long-form pillar article into a regular blog post for "
    "the same yacht brokerage -- the post that sits alongside their own "
    "everyday writing, so unlike the pillar piece it was condensed from, it "
    "must genuinely read as theirs. Target the given word count exactly: "
    "this broker's own typical article length, from their voice profile.\n\n"
    "This is a condensation of the long-form pillar article given to you "
    "below, not a separate piece -- keep the same angle, the same claims, "
    "and the same voice as that article. Do not introduce facts, figures, or "
    "claims that are not already in the long-form article. Match the "
    "register, structure, and vocabulary described in the voice profile "
    "precisely -- unlike the pillar piece, voice matching here is binding, "
    "not just encouraged, because this is the format a reader of this "
    "broker's blog must not be able to tell apart from their own writing.\n\n"
    "If Sunreef appears in the long-form article as one example among "
    "several, it must stay that way in the condensation -- never foreground "
    "Sunreef as the subject of the post, and never let condensing turn a "
    "passing example into something that reads as an advertisement for "
    "Sunreef, even though every fact in the post was already in the "
    "long-form article.\n\n"
    "Never disparage or position against named competitors -- "
    f"{', '.join(COMPETITORS)} are never named or argued against, regardless "
    "of how relevant the comparison might seem."
    + "\n\n" + _KEYWORD_INSTRUCTION
)

_SHORT_SYSTEM = (
    "You condense a long-form article into a newsletter blurb for the same "
    "yacht brokerage: a headline plus "
    f"{SHORT_MIN_WORDS}-{SHORT_MAX_WORDS} words. "
    "This is a condensation of the long-form article given to you below, not "
    "a separate piece -- keep the same angle, the same claims, and the same "
    "voice as that article. Do not introduce facts, figures, or claims that "
    "are not already in the long-form article, and match the register and "
    "vocabulary described in the voice profile.\n\n"
    "If Sunreef appears in the long-form article as one example among "
    "several, it must stay that way in the condensation -- never foreground "
    "Sunreef as the subject of the blurb, and never let condensing turn a "
    "passing example into something that reads as an advertisement for "
    "Sunreef, even though every fact in the blurb was already in the "
    "long-form article.\n\n"
    "Never disparage or position against named competitors -- "
    f"{', '.join(COMPETITORS)} are never named or argued against, regardless "
    "of how relevant the comparison might seem."
    + "\n\n" + _KEYWORD_INSTRUCTION
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


def _word_count_line(profile: dict) -> str | None:
    """"Target length: about N words ..." or None if the profile has none.

    Split out of `_profile_summary` because the three formats no longer share
    one length target: `write_long` targets the fixed pillar range
    (LONG_MIN_WORDS-LONG_MAX_WORDS), not this broker's own typical_word_count,
    while `write_medium` is the format that target actually belongs to (spec
    v0.6 §5).
    """
    if not isinstance(profile, dict):
        return None
    word_count = profile.get("typical_word_count")
    if not word_count:
        return None
    return (
        f"Target length: about {word_count} words "
        "(this broker's own typical article length)."
    )


def _profile_summary(profile: dict) -> str:
    """The voice profile as prose, so the draft matches this broker's voice.

    Deliberately excludes typical_word_count -- see `_word_count_line`, which
    each `write_*` method includes only where that target actually applies.
    """
    if not isinstance(profile, dict):
        return ""
    lines = []
    if register := profile.get("register"):
        lines.append(f"Register: {register}")
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


def _keyword_guidance(keywords: dict | None) -> str | None:
    """The selected primary/secondary keywords as a user-turn instruction
    block, or None when there is nothing to add.

    `keywords` is the shape `bce.keywords.select_for_draft` returns:
    `{"primary": row_or_None, "secondary": [rows]}`. Both "the caller passed
    nothing" and "the caller passed a selection where nothing qualified"
    (spec §5b: primary is None) degrade to the same None here -- either way
    the draft is written with no keyword guidance, never a forced substitute.
    """
    if not keywords:
        return None
    primary = keywords.get("primary")
    if not primary:
        return None
    lines = [
        "Keywords to work in naturally -- they must read as ordinary "
        "language a person would actually write, never stuffed in "
        "mechanically:",
        f'- Primary: "{primary["phrase"]}" -- work this in where it fits '
        "naturally, ideally in the title or the first paragraph.",
    ]
    for kw in keywords.get("secondary") or []:
        lines.append(f'- Secondary: "{kw["phrase"]}"')
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
        # A max_tokens cutoff is also HTTP 200, but *with* a text block --
        # just one truncated mid-thought. Unlike the JSON-schema clients,
        # prose truncation is not self-evidently broken, so it must be
        # checked explicitly rather than trusted as a successful draft (F2).
        if response.stop_reason == "max_tokens":
            return None
        text = _extract_text(response)
        return text or None

    def write_long(
        self, angle: dict, profile: dict, broker_name: str, keywords: dict | None = None
    ) -> str | None:
        """A comprehensive 2000-2300 word pillar article, or None on failure.

        No call is made without an angle: there is nothing to draft against.
        Targets the fixed pillar length (LONG_MIN_WORDS-LONG_MAX_WORDS), not
        this broker's typical_word_count -- spec v0.6 §5 moved that target to
        `write_medium`.

        `keywords` is optional (spec §5b): the primary/secondary selection
        `bce.keywords.select_for_draft` returns for this angle, or None. When
        given, its guidance is appended to the prompt; when absent, or when
        nothing qualified, the draft is written exactly as before.
        """
        if not angle:
            return None
        user_content = (
            f"Broker: {broker_name}\n\n"
            f"Angle:\n{_angle_summary(angle)}\n\n"
            f"Pillar length target: {LONG_MIN_WORDS}-{LONG_MAX_WORDS} words.\n\n"
            f"Voice profile (match as far as reasonably possible; not "
            f"binding at this length):\n{_profile_summary(profile)}"
        )
        if guidance := _keyword_guidance(keywords):
            user_content += f"\n\n{guidance}"
        return self._create(
            system=_LONG_SYSTEM + untrusted.INSTRUCTION, user_content=user_content, max_tokens=MAX_TOKENS_LONG
        )

    def write_medium(
        self, long_body: str, profile: dict, broker_name: str, keywords: dict | None = None
    ) -> str | None:
        """A regular-length blog post condensed from `long_body`, matched to
        this broker's own typical_word_count -- or None on any failure.

        Generated from the long draft's body, not the angle (spec §5), same
        as `write_short`: the medium form must carry the same claims as the
        long form, which only the body actually contains. No call is made
        for an empty long body: there is nothing to condense.

        `keywords` (spec §5b): this format's own selection -- a subset of the
        long draft's (see `bce.keywords.select_for_draft`), not the same
        object passed to `write_long`.
        """
        if not long_body:
            return None
        lines = [f"Broker: {broker_name}", "", f"Long-form article to condense:\n\n{long_body}"]
        if word_count_line := _word_count_line(profile):
            lines.append(word_count_line)
        lines.append(f"Voice profile:\n{_profile_summary(profile)}")
        if guidance := _keyword_guidance(keywords):
            lines.append(guidance)
        user_content = "\n\n".join(lines)
        return self._create(
            system=_MEDIUM_SYSTEM + untrusted.INSTRUCTION, user_content=user_content, max_tokens=MAX_TOKENS_MEDIUM
        )

    def write_short(
        self, long_body: str, profile: dict, keywords: dict | None = None
    ) -> str | None:
        """A headline plus 100-200 words condensed from `long_body`.

        Generated from the long draft's body, not the angle (spec §5): the
        short form must carry the same claims as the long form, which only
        the body -- not the angle it was written from -- actually contains.
        No call is made for an empty long body: there is nothing to condense.

        `keywords` (spec §5b): the short format never carries secondaries
        (`FORMAT_KEYWORD_COUNTS["short"]`), so in practice this is just the
        primary -- still passed through the same shape as the other formats.
        """
        if not long_body:
            return None
        user_content = (
            f"Long-form article to condense:\n\n{long_body}\n\n"
            f"Voice profile:\n{_profile_summary(profile)}"
        )
        if guidance := _keyword_guidance(keywords):
            user_content += f"\n\n{guidance}"
        return self._create(
            system=_SHORT_SYSTEM + untrusted.INSTRUCTION, user_content=user_content, max_tokens=MAX_TOKENS_SHORT
        )
