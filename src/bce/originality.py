"""The three originality gates (spec §10.3): Unique, Tailored, Original.

"Unique, tailored, original" are three different guarantees requiring three
different mechanisms (spec §10.3), and this module keeps them as three
distinct functions rather than one blended score, so a human reading a
rejected draft's row can tell *which* guarantee failed:

- **Unique** (`check_uniqueness`) -- corpus-wide embedding cosine similarity,
  scoped within `format` (spec v0.6 §5: long vs long, medium vs medium,
  short vs short -- comparing across formats would flag every article as a
  duplicate of its own summary/pillar). Blocking for every format.
- **Tailored** (`score_tailored`) -- register/structure match against this
  broker's own `voice_profile`, computed from already-stored features, no
  API call. Blocking for `medium`/`short` only -- spec v0.6 §5 made voice
  matching "encouraged but not binding" for `long`, since a 2000-2300 word
  pillar piece is nowhere near any broker's own `typical_word_count`.
- **Original** (`check_original`) -- near-duplication against this specific
  broker's own already-published prose, via shingle-hash set overlap (see
  `bce.fingerprint` for why hashes, not text). Scoped to one broker, unlike
  Gate 1's corpus-wide comparison. Blocking for every format.

`run_gates` runs all three and combines them into one `GateResult`, which is
also where the format-dependent Tailored exception actually happens
(`TAILORED_BLOCKING_FORMATS`) -- the individual gate functions never see
`format` used for anything except Gate 1's bucket key.

**On the two thresholds this module introduces beyond spec §10.3's 0.88**
(`TAILORED_MIN_SCORE`, `ORIGINALITY_MAX_CONTAINMENT`): neither existed
before this task, and neither has been calibrated against real drafts --
they are first-pass estimates, deliberately named constants (not inline
literals) so they are easy to find and revise once real gate outcomes exist
to tune them against.
"""
import json
import math
from dataclasses import dataclass

from bce import claims, style
from bce.fingerprint import containment as _shingle_containment
from bce.fingerprint import shingle_hashes

#: Spec §10.3, stated exactly: "Embedding cosine similarity across the draft
#: corpus; threshold 0.88". A similarity >= this value fails the gate.
UNIQUENESS_THRESHOLD = 0.88

#: First-pass estimate, NOT calibrated against real drafts (see module
#: docstring). Below this register/structure match score (0-1, from
#: `score_tailored`), a draft is judged not to read like this broker.
TAILORED_MIN_SCORE = 0.5

#: Spec v0.6 §5: Tailored is "encouraged but not binding" for `long` (a
#: pillar piece serves depth first, and no broker's own typical article is
#: anywhere near 2000-2300 words) and binding for `medium` ("this is the one
#: that has to read like them") and `short`.
TAILORED_BLOCKING_FORMATS = {"medium", "short"}

#: First-pass estimate, NOT calibrated against real drafts (see module
#: docstring). `bce.fingerprint.containment` (not Jaccard) above this
#: fraction means more than half of the draft's shingles already exist
#: somewhere in this broker's own published prose.
ORIGINALITY_MAX_CONTAINMENT = 0.5


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Plain-Python cosine similarity -- no numpy dependency for a ~50-
    vector corpus (spec §7: "At the 50-draft cap this is cosine similarity
    over ~50 vectors; a vector database would be premature", the same
    reasoning applies to the arithmetic itself).
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def check_uniqueness(
    conn, format: str, body: str, embedding_client
) -> dict:
    """Gate 1: corpus-wide cosine similarity, scoped within `format`.

    Returns ``{"passes": bool, "max_similarity": float | None,
    "most_similar_draft_id": int | None, "embedding": list[float] | None}``.

    `embedding` is handed back whenever it was computed, **regardless of
    `passes`** -- the caller persists it to this draft's own row either way,
    which is what makes "a draft rejected for similarity still counts as
    seen" (spec §10.3) true: the next comparison in this format bucket will
    see it.

    If the embedding call itself fails -- no API key, network error, safety
    refusal; `EmbeddingClient.embed` degrades every one of those to `None`
    -- uniqueness cannot be verified. An unverifiable draft does not pass a
    *blocking* gate: this returns `passes=False` with nothing to persist,
    rather than silently treating "we couldn't check" the same as "we
    checked and it's fine".
    """
    vector = embedding_client.embed(body)
    if vector is None:
        return {
            "passes": False,
            "max_similarity": None,
            "most_similar_draft_id": None,
            "embedding": None,
        }

    rows = conn.execute(
        "SELECT id, embedding FROM draft WHERE format=? AND embedding IS NOT NULL",
        (format,),
    ).fetchall()

    max_similarity = None
    most_similar_id = None
    for row in rows:
        try:
            other = json.loads(row["embedding"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(other, list) or not other:
            continue
        similarity = _cosine_similarity(vector, other)
        if max_similarity is None or similarity > max_similarity:
            max_similarity = similarity
            most_similar_id = row["id"]

    passes = max_similarity is None or max_similarity < UNIQUENESS_THRESHOLD
    return {
        "passes": passes,
        "max_similarity": max_similarity,
        "most_similar_draft_id": most_similar_id,
        "embedding": vector,
    }


def _body_paragraphs(body: str) -> list[str]:
    """Same paragraph split as `bce.web.app._paragraphs` / `bce.drafting`'s
    rendering: draft bodies are prose with blank-line breaks, not real
    markdown, so this is the same "split on \\n\\n" convention rather than a
    markdown parser.
    """
    if not body:
        return []
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def _ratio_score(actual, target) -> float | None:
    """1.0 for an exact match, decaying toward 0.0 as `actual` diverges
    proportionally from `target`; `None` when there is nothing to compare
    (either value missing, or `target` is zero) so the caller can exclude
    this sub-score from the average instead of fabricating one from absent
    data.
    """
    if actual is None or target is None or target == 0:
        return None
    return max(0.0, 1 - abs(actual - target) / target)


def score_tailored(profile: dict, body: str) -> float:
    """Gate 2: how well `body` matches this broker's stored voice-profile
    statistics (spec §10.3 *Tailored*: "Score register/structure match ...
    computable from stored features").

    Purely computed from `avg_sentence_len`, `typical_word_count`, and
    `structure_pattern`'s `paragraphs_per_article` / `words_per_paragraph`
    -- no API call, no additional stored state. Returns a score in [0, 1];
    a comparable target missing from the profile simply drops that
    sub-score from the average rather than penalising a broker whose stored
    profile happens to be thin on one dimension. Whether this score
    *blocks* the draft is a decision `run_gates` makes based on `format`,
    not this function -- callers wanting the raw score for `long` (spec
    v0.6 §5: "compute and record ... never block") get it from here
    unconditionally.
    """
    if not body:
        return 0.0
    draft_avg_sentence = style.avg_sentence_length([body])
    draft_word_count = len(body.split())
    draft_structure = json.loads(style.structure_pattern([_body_paragraphs(body)]))

    profile = profile if isinstance(profile, dict) else {}
    profile_structure = profile.get("structure_pattern")
    profile_structure = profile_structure if isinstance(profile_structure, dict) else {}

    scores = [
        s for s in (
            _ratio_score(draft_avg_sentence, profile.get("avg_sentence_len")),
            _ratio_score(draft_word_count, profile.get("typical_word_count")),
            _ratio_score(
                draft_structure.get("paragraphs_per_article"),
                profile_structure.get("paragraphs_per_article"),
            ),
            _ratio_score(
                draft_structure.get("words_per_paragraph"),
                profile_structure.get("words_per_paragraph"),
            ),
        )
        if s is not None
    ]
    if not scores:
        # No comparable target in the profile at all: the broker was profiled
        # with a judgement half (register/themes) but no statistics half, which
        # `drafting.draft_for_broker` explicitly permits -- it refuses to draft
        # only when `register` is NULL.
        #
        # `None` means "not comparable", NOT "scored zero". Returning 0.0 here
        # would be indistinguishable from a genuinely terrible voice match and
        # would reject every medium and short draft for such a broker, against
        # this function's own rule that a missing target drops its sub-score
        # rather than penalising the draft. `run_gates` treats None as
        # non-blocking and records it, so a human sees "not comparable" instead
        # of a fabricated zero.
        return None
    return round(sum(scores) / len(scores), 4)


def check_original(conn, broker_id: int, body: str) -> dict:
    """Gate 3: near-duplication against this broker's own published prose
    (spec §10.3 *Original*), via shingle-hash set containment -- see
    `bce.fingerprint` for why hashes, not text, are stored and compared.

    Returns ``{"passes": bool, "containment": float | None}``.
    `containment` is `None` (not 0.0) when there was nothing to compare --
    an empty draft, or a broker with no `source_fingerprint` rows yet (never
    profiled, or profiled before this gate existed) -- distinguishing
    "compared and found no overlap" from "could not compare at all", the
    same distinction Gate 1 makes for a first-of-its-format draft.

    Scoped to `broker_id` alone, unlike Gate 1: the question is "did we hand
    *this* broker back *their own* words", which only their own fingerprints
    can answer -- a coincidental phrase overlap with a different broker's
    prose is not this gate's concern.
    """
    draft_hashes = shingle_hashes(body)
    if not draft_hashes:
        return {"passes": True, "containment": None}

    rows = conn.execute(
        "SELECT shingle_hash FROM source_fingerprint WHERE broker_id=?",
        (broker_id,),
    ).fetchall()
    source_hashes = {row["shingle_hash"] for row in rows}
    if not source_hashes:
        return {"passes": True, "containment": None}

    overlap = _shingle_containment(draft_hashes, source_hashes)
    return {"passes": overlap <= ORIGINALITY_MAX_CONTAINMENT, "containment": overlap}


@dataclass(frozen=True)
class GateResult:
    """The combined outcome of every gate for one draft (spec §10.3, §10.9).

    Frozen, with an explicit `__bool__` -- same rationale as `drafting.
    DraftResult` / `profile.ProfileResult`: a dataclass's default truthiness
    is not tied to any field, so without this a caller doing `if result:`
    would be silently wrong. `passes` is the single blocking verdict a
    caller uses to decide the draft's status; the per-gate fields are what
    gets persisted to the draft row and shown to a human (spec:
    "Surface gate results ... which gates passed, the similarity figure,
    and what it collided with").
    """

    passes: bool
    passes_uniqueness: bool
    max_similarity: float | None
    most_similar_draft_id: int | None
    embedding: list[float] | None
    passes_tailored: bool
    tailored_score: float
    passes_originality: bool
    originality_overlap: float | None
    passes_no_product_claims: bool
    product_claims: tuple

    def __bool__(self) -> bool:
        return self.passes


def run_gates(
    conn, *, broker_id: int, format: str, body: str, profile: dict, embedding_client
) -> GateResult:
    """Run all three gates for one already-drafted format and combine them.

    Gate 1 (Unique), Gate 3 (Original) and Gate 4 (No product claims, spec
    §10.4 as revised / §10.9) are blocking for every format. Gate 2
    (Tailored) is blocking only for `format` in `TAILORED_BLOCKING_FORMATS`
    (medium/short) -- for `long` the score is still computed and returned (so
    it can be persisted and shown), it just never contributes to `passes`.

    Gate 4 is mechanical and format-independent: a fabricated specification
    is no less dangerous in a 150-word newsletter item than in a pillar, so
    unlike Tailored it has no advisory mode.
    """
    uniqueness = check_uniqueness(conn, format, body, embedding_client)
    tailored_score = score_tailored(profile, body)
    original = check_original(conn, broker_id, body)
    product_claims = claims.check_no_product_claims(body)

    # `None` is "not comparable" (no statistics in the profile), not a zero.
    # It never blocks, and it is persisted as NULL so a reviewer can tell an
    # unverifiable draft from one that genuinely reads nothing like the broker.
    passes_tailored = (
        True if tailored_score is None else tailored_score >= TAILORED_MIN_SCORE
    )
    tailored_blocks = (
        format in TAILORED_BLOCKING_FORMATS and tailored_score is not None
    )
    tailored_ok = passes_tailored if tailored_blocks else True

    overall = (
        uniqueness["passes"]
        and tailored_ok
        and original["passes"]
        and product_claims["passes"]
    )

    return GateResult(
        passes=overall,
        passes_uniqueness=uniqueness["passes"],
        max_similarity=uniqueness["max_similarity"],
        most_similar_draft_id=uniqueness["most_similar_draft_id"],
        embedding=uniqueness["embedding"],
        passes_tailored=passes_tailored,
        tailored_score=tailored_score,
        passes_originality=original["passes"],
        originality_overlap=original["containment"],
        passes_no_product_claims=product_claims["passes"],
        product_claims=tuple(product_claims["claims"]),
    )
