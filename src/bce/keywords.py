"""Keyword targeting (spec §5b, §8): thresholds, the Semrush bank importer,
and per-draft keyword selection.

**Thresholds.** `MAX_DIFFICULTY` / `MIN_VOLUME` are named constants, never
inline literals -- spec §5b requires both be displayed in the UI, so they
must have exactly one home. `qualifies()` is the single predicate that
applies them; `load_bank` (at import time) and `select_for_draft` (indirectly,
by only ever drawing from rows already marked `qualifies=1`) both go through
it, so the rule genuinely exists once.

**Importer.** `load_bank` ingests a *real* Semrush export, not just our own
committed `data/keyword_bank.csv`. The operator runs their own keyword
research interactively and exports a CSV; that export is the input, and it is
assumed messy on every axis the brief called out: header names differ between
Keyword Magic Tool / Keyword Overview / Position Tracking, the delimiter is
comma or semicolon depending on export path, Excel prepends a UTF-8 BOM, and
numeric fields carry thousands separators, decimals, or one of several
"missing" spellings (blank, `n/a`, `-`). A row that genuinely cannot be
parsed is skipped and the reason reported -- never guessed at -- but the
importer's job is to *store* what the operator exported, not to pre-judge it:
every parsable row is imported and `qualifies` is set on it, whether or not
it clears the thresholds, so the CLI can report the split honestly instead of
silently discarding what the operator's research yielded.

**Competitor gating.** A real export carries no `competitor_brand` column, so
`detect_competitor_brand` recognises Sunreef's direct catamaran-brand rivals
by name, gating them out of automatic selection until a human opts one in
(spec §5b "Competitor brand terms") -- see the docstring above
`COMPETITOR_BRANDS` for how the false-positive risk on `excess` / `privilege`
(both ordinary English words) is handled.

**Selection.** `select_for_draft` ranks the eligible bank deterministically
against an angle's text and slices a per-format prefix off that one ranking,
which is what gives medium/short their subset-of-long guarantee "for free" --
see the function's docstring.
"""
import csv
import io
import re
import sqlite3
from dataclasses import dataclass, field

#: Spec §5b: "Keyword difficulty < 30" -- exclusive.
MAX_DIFFICULTY = 30
#: Spec §5b: "Average monthly search volume > 100" -- exclusive.
MIN_VOLUME = 100

#: Fixed for now (spec §5b "Now -- banked"): the bank is a manually-run,
#: point-in-time Semrush export, not a live lookup, so every row this module
#: writes carries the same provenance regardless of which CSV it came from.
_DATABASE = "us"
_MEASURED_AT = "2026-09-01"
_SOURCE = "semrush"

FORMAT_KEYWORD_COUNTS = {
    # format -> (primary_count, max_secondary_count), spec §5b "Keywords per format".
    "long": (1, 4),
    "medium": (1, 2),
    "short": (1, 0),
}


def qualifies(volume, difficulty) -> bool:
    """Spec §5b's single qualifying predicate: difficulty < 30 and volume > 100.

    `None` in either field means "unmeasured", not "assume it passes" -- a
    keyword whose difficulty could not be read is not a keyword we can claim
    clears the bar.
    """
    if volume is None or difficulty is None:
        return False
    return difficulty < MAX_DIFFICULTY and volume > MIN_VOLUME


# =============================================================================
# Header aliasing -- different Semrush tools export different column names
# for the same field. Matched case-insensitively; anything not in this map is
# an unrecognized extra column and is silently ignored, not fatal.
# =============================================================================

_FIELD_ALIASES: dict[str, frozenset[str]] = {
    "phrase": frozenset({"phrase", "keyword"}),
    "volume": frozenset({"volume", "search volume"}),
    "difficulty": frozenset({
        "difficulty", "keyword difficulty", "keyword difficulty index",
        "kd", "kd %", "kd%",
    }),
    "intent": frozenset({"intent"}),
    "competitor_brand": frozenset({
        "competitor_brand", "competitor brand", "competitor",
    }),
}


class NoPhraseColumnError(ValueError):
    """The CSV has no column this module recognises as the keyword phrase."""

    def __init__(self, found: list[str]):
        self.found = found
        super().__init__(
            "CSV must have a 'phrase' or 'Keyword' column (case-insensitive); "
            "found: " + (", ".join(found) if found else "(no header row)")
        )


def _normalize_header(name: str) -> str:
    return (name or "").strip().lstrip("﻿").strip().lower()


def _map_headers(fieldnames: list[str] | None) -> dict[str, str]:
    """raw header text (as csv.DictReader will key rows with) -> canonical
    field name, for every header this module recognises. Headers not in
    `_FIELD_ALIASES` are simply absent from the map -- callers ignore them by
    construction, since they only ever look a canonical name up.
    """
    mapping: dict[str, str] = {}
    for raw in fieldnames or []:
        norm = _normalize_header(raw)
        for canonical, aliases in _FIELD_ALIASES.items():
            if norm in aliases:
                mapping[raw] = canonical
                break
    return mapping


def _sniff_delimiter(text: str) -> str:
    """Comma or semicolon, whichever the first non-blank line uses more of.

    Real exports are either one or the other throughout the file (never
    mixed row-to-row), so counting on just the header line is enough, and is
    far more predictable across small/edge-case fixtures than `csv.Sniffer`.
    """
    first_line = next((ln for ln in text.splitlines() if ln.strip()), "")
    return ";" if first_line.count(";") > first_line.count(",") else ","


_MISSING_TOKENS = frozenset({"", "n/a", "na", "-", "--", "?"})


def _parse_number(raw) -> tuple[float | None, bool]:
    """A cleaned numeric value, or (None, True) for a recognized "missing"
    spelling (blank / n/a / -), or (None, False) when `raw` is genuinely
    unparseable -- the caller's signal to skip the row rather than guess.

    Thousands separators and a trailing '%' are stripped *after* the CSV
    parser has already split the row on its delimiter, per the brief: a
    comma-delimited file quotes a value like "8,100" so the parser hands this
    function the already-unquoted string `8,100`, and only then does this
    function remove the separator -- never the other way around.
    """
    if raw is None:
        return None, True
    s = str(raw).strip()
    if s.lower() in _MISSING_TOKENS:
        return None, True
    cleaned = s.replace(",", "").replace(" ", "")
    if cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    try:
        return float(cleaned), True
    except ValueError:
        return None, False


_INTENT_WORDS = {
    "commercial": 0, "informational": 1, "navigational": 2, "transactional": 3,
}


def _parse_intent(raw):
    """A 0-3 intent code, or None. Never blocks import -- unlike volume and
    difficulty, intent plays no part in `qualifies`, so an unrecognised
    spelling degrades to "unknown" rather than skipping an otherwise-good row.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    value, ok = _parse_number(s)
    if ok and value is not None:
        return int(value)
    return _INTENT_WORDS.get(s.lower())


#: Reverse of `_INTENT_WORDS`: our own committed bank's single numeric code
#: (0-3), mapped back to the textual label Semrush itself uses, so a numeric-
#: coded row and a real Semrush export both feed the same editorial
#: predicate below instead of two parallel representations.
_INTENT_LABELS_BY_CODE = {v: k for k, v in _INTENT_WORDS.items()}

_KNOWN_INTENT_LABELS = frozenset(_INTENT_WORDS)


def _parse_intent_label_set(raw) -> frozenset[str] | None:
    """The Intent cell as a set of lowercase labels, or None if blank/absent.

    Semrush emits Intent as a comma-joined string on one cell --
    "Informational, Commercial" -- which must be parsed as a *set*, not
    compared as a string: `"Informational, Transactional" == "Informational"`
    is false but so is a naive substring check's safety (a longer label list
    can still fail to register a label that IS present if compared the wrong
    way). Splitting on comma and normalising each part is the only reliable
    way to ask "does this row's intent include X".

    Also accepts our own committed bank's single numeric code (0-3) for
    backward compatibility, so `data/keyword_bank.csv` classifies sensibly
    too, not just real Semrush textual exports.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    numeric, ok = _parse_number(s)
    if ok and numeric is not None:
        label = _INTENT_LABELS_BY_CODE.get(int(numeric))
        return frozenset({label}) if label else None
    labels = frozenset(
        part.strip().lower() for part in s.split(",") if part.strip()
    )
    return labels or None


def is_editorial_intent(intent_labels: frozenset[str] | None) -> bool:
    """Spec §5b "Editorial intent only": eligible only when Informational is
    present and both Transactional and Navigational are absent. Commercial is
    *retained* regardless -- comparison content ("power catamaran vs sailing
    catamaran") is the most editorial material in the bank, not excluded.

    `None` or an empty set (no Intent cell at all, or nothing recognised in
    it) is treated as unknown, not editorial -- never assumed informational
    just because nothing says otherwise (spec change brief: "guessing in the
    permissive direction is how a product page ends up as an article").
    """
    if not intent_labels:
        return False
    return (
        "informational" in intent_labels
        and "transactional" not in intent_labels
        and "navigational" not in intent_labels
    )


def _parse_bool(raw) -> bool:
    if raw is None:
        return False
    return str(raw).strip().lower() in ("1", "true", "yes", "y")


#: Segment relevance (coordinator follow-up to spec §5b): clearing the
#: volume/difficulty thresholds does not mean a phrase is actually about
#: Sunreef's segment -- 60ft+ luxury catamarans. "catamaran stripe light
#: blue-ivory area rug" clears both thresholds easily and is a rug.
#:
#: Grouped by reason, not a bare boolean list, because the operator needs to
#: see *why* something was excluded to correct a bad rule -- a wrong
#: exclusion is a data problem (see `db.py`'s `segment_relevant`/
#: `segment_relevant_reason`: it is stored and correctable, not baked in
#: irreversibly), not something this module can get right for every phrase
#: that will ever appear in a bank.
#:
#: Deliberately does NOT include "net" or "netting" anywhere: those are real
#: boat components (trampoline / safety netting on a catamaran), not proof of
#: an off-segment result -- a naive `\bnet\b` rule was the exact
#: over-exclusion trap this list must not fall into.
#:
#: `non_english` and `other_brand` are kept as named, empty categories: no
#: current export has an example, but the reason exists so a future one has
#: somewhere to go rather than forcing a new category to be invented ad hoc.
SEGMENT_EXCLUSION_PATTERNS: dict[str, tuple[str, ...]] = {
    # Not a boat at all: a rug, a typeface, a pharmacy benefit manager, a
    # street name -- all happen to contain "catamaran" as a substring of a
    # street/product name, not a reference to one.
    "not_a_boat": (
        "rug", "area rug", "font", "rx", "dr", "drive", "song",
        "outfit", "outfits", "images pictures", "camphor",
        "keep balance on a ship",
    ),
    # A real boat, but not the 60ft+ luxury size class Sunreef sells --
    # inflatables, paddleboards, and small beach/day cats.
    #
    # NOTE: "net"/"netting" are deliberately ABSENT. Catamaran trampoline
    # netting is a genuine component of a real yacht; a naive "net" rule
    # mislabels it "not a boat". Over-exclusion of on-topic terms is a worse
    # failure here than letting an occasional rug through, because the rug is
    # obvious on review and the missing term is invisible.
    "wrong_size_class": (
        "paddle board", "paddleboard", "sup", "blow up", "inflatable",
        "2 man", "2 person", "two person", "beach catamaran", "kayak",
        "small", "smallest", "catamaran small", "dinghy", "skiff",
        "surf", "portable", "cheap", "kite", "kitesurf", "30 foot",
    ),
    # A booked tourist activity ("ride on a catamaran"), not a purchase or
    # ownership topic a broker would publish about.
    #
    # NOTE the deliberate "cruise" vs "cruising" split, which token-exact
    # matching gives us for free: "catamaran sunset cruise" is a day-trip
    # booking and is excluded, while "cruising catamaran" and "cruising in a
    # catamaran" are ownership topics and are kept. Likewise "charter" is NOT
    # excluded -- a week-long yacht charter is core broker business, unlike a
    # two-hour tour.
    "excursion_tourism": (
        "luau", "snorkel", "snorkeling", "sightseeing", "excursion",
        "day trip", "santorini", "oia", "sunset", "cruise", "cruises",
        "tour", "tours", "trip", "trips", "vacation", "vacations",
        "holidays", "flotilla", "party boat", "whale watching",
        "isla mujeres", "punta cana", "riviera maya", "culebra",
        "belize", "barbados", "turtle canyon", "palm beach",
    ),
    # A racing class, not a cruising/ownership topic.
    "racing": (
        "f50", "a class", "class a", "hobie", "nacra",
        "racing", "race", "regatta",
    ),
    # Not English, or a misspelling Semrush surfaced as its own term. Nothing
    # editorial to write for a US broker audience.
    "non_english": (
        "que es", "catamara", "catams", "whats",
    ),
    # A named operator, marina, club or unrelated brand that merely contains
    # "catamaran" -- not a topic, a proper noun.
    "other_brand": (
        "glacier bay", "makani", "barefoot", "cool runnings", "navy",
        "catamaran club", "catamaran park",
    ),
}


def _phrase_matches_pattern(tokens: list[str], pattern: str) -> bool:
    pattern_tokens = _tokenize(pattern)
    n = len(pattern_tokens)
    if n == 0:
        return False
    return any(
        tokens[i:i + n] == pattern_tokens for i in range(len(tokens) - n + 1)
    )


def classify_segment_relevance(phrase: str) -> str | None:
    """The exclusion reason if `phrase` is off-segment for Sunreef despite
    clearing the §5b thresholds, or None if it looks on-segment.

    Word-boundary, case-insensitive, matched the same way as
    `detect_competitor_brand` (token subsequence, not substring) -- so
    "net"/"netting" never collide with a pattern that isn't there, and a
    plural or compound word ("paddleboard" vs "paddle board") needs its own
    listed variant rather than matching by accident.

    This is heuristic and will misfire sometimes (see `SEGMENT_EXCLUSION_
    PATTERNS`'s docstring) -- callers must treat the result as a starting
    judgement to store and show, not an infallible verdict.
    """
    tokens = _tokenize(phrase)
    for reason, patterns in SEGMENT_EXCLUSION_PATTERNS.items():
        if any(_phrase_matches_pattern(tokens, p) for p in patterns):
            return reason
    return None


@dataclass(frozen=True)
class LoadBankResult:
    """What one `load_bank` call actually did -- the shape the CLI's split
    report is built from (spec change brief: "total imported, how many
    qualify, how many don't, and the threshold each failure missed").

    `imported` counts only rows that were successfully parsed and written (or
    re-written, on a repeat/overlapping import) -- never a skipped row.
    `qualifying` + `non_qualifying` always sum to `imported`. Among the
    non-qualifying rows, `missed_difficulty` / `missed_volume` count how many
    failed each threshold -- a row failing both (or having one field
    unmeasured) is counted in both, since both are genuinely true of it.
    `skipped` is one human-readable reason per row that could not be parsed
    at all, so nothing is silently dropped.
    """

    imported: int = 0
    qualifying: int = 0
    non_qualifying: int = 0
    missed_difficulty: int = 0
    missed_volume: int = 0
    #: The second, independent gate (see `classify_segment_relevance`):
    #: `segment_relevant` + `segment_excluded` always sum to `imported`,
    #: exactly like `qualifying` + `non_qualifying` do -- but this is a
    #: different question (is this actually about the segment?) than
    #: `qualifying` answers (does it clear the metrics thresholds?), and a
    #: row can be qualifying and segment-excluded at the same time.
    #: `excluded_by_reason` / `excluded_volume_by_reason` key on the reason
    #: strings from `SEGMENT_EXCLUSION_PATTERNS`.
    segment_relevant: int = 0
    segment_excluded: int = 0
    excluded_by_reason: dict = field(default_factory=dict)
    excluded_volume_by_reason: dict = field(default_factory=dict)
    #: The third, independent gate (spec §5b "Editorial intent only"):
    #: `editorial` + `non_editorial` sum to `imported`, same shape as the
    #: qualify and segment splits above.
    editorial: int = 0
    non_editorial: int = 0
    skipped: tuple = field(default_factory=tuple)


def _read_and_strip_comments(csv_path: str) -> str:
    with open(csv_path, "rb") as f:
        raw = f.read()
    # utf-8-sig: strips a leading BOM if present (Excel's "CSV UTF-8"
    # export), and is a no-op otherwise -- same handling as `bce import`.
    text = raw.decode("utf-8-sig")
    lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    return "\n".join(lines)


def load_bank(conn: sqlite3.Connection, csv_path: str) -> LoadBankResult:
    """Import a Semrush keyword export into the `keyword` table.

    Idempotent: `phrase` + `database` is the row's identity (spec §8), so a
    repeat import of the same file, or an overlapping later export, upserts
    in place rather than duplicating rows or multiplying stored metrics.

    Every row that can be parsed is imported, whether or not it clears the
    §5b thresholds -- `qualifies` records the verdict, it does not gate
    storage. A row is skipped (and its reason recorded on the result) only
    when it cannot be parsed at all: no usable phrase, or a volume/difficulty
    cell that is neither a real number nor a recognized "missing" spelling.
    """
    text = _read_and_strip_comments(csv_path)
    delimiter = _sniff_delimiter(text)
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    header_map = _map_headers(reader.fieldnames)
    if "phrase" not in header_map.values():
        raise NoPhraseColumnError(reader.fieldnames or [])

    imported = qualifying = non_qualifying = 0
    missed_difficulty = missed_volume = 0
    segment_relevant_count = segment_excluded_count = 0
    excluded_by_reason: dict[str, int] = {}
    excluded_volume_by_reason: dict[str, int] = {}
    editorial_count = non_editorial_count = 0
    skipped: list[str] = []

    for line_no, raw_row in enumerate(reader, start=2):  # header is line 1
        canon: dict[str, str] = {}
        for raw_key, value in raw_row.items():
            field_name = header_map.get(raw_key)
            if field_name is not None and field_name not in canon:
                canon[field_name] = value

        phrase = (canon.get("phrase") or "").strip()
        if not phrase:
            skipped.append(f"line {line_no}: missing phrase")
            continue

        volume, volume_ok = _parse_number(canon.get("volume"))
        if not volume_ok:
            skipped.append(
                f"line {line_no} ({phrase!r}): unparseable volume "
                f"{canon.get('volume')!r}"
            )
            continue
        difficulty, difficulty_ok = _parse_number(canon.get("difficulty"))
        if not difficulty_ok:
            skipped.append(
                f"line {line_no} ({phrase!r}): unparseable difficulty "
                f"{canon.get('difficulty')!r}"
            )
            continue

        volume_val = int(round(volume)) if volume is not None else None
        intent_val = _parse_intent(canon.get("intent"))
        q = qualifies(volume_val, difficulty)
        explicit_competitor = _parse_bool(canon.get("competitor_brand"))
        competitor = 1 if (explicit_competitor or detect_competitor_brand(phrase)) else 0
        segment_reason = classify_segment_relevance(phrase)
        segment_relevant_flag = 1 if segment_reason is None else 0

        intent_label_set = _parse_intent_label_set(canon.get("intent"))
        editorial_flag = 1 if is_editorial_intent(intent_label_set) else 0
        intent_labels_text = (
            ", ".join(sorted(intent_label_set)) if intent_label_set else None
        )

        # `segment_relevant` / `segment_relevant_reason` are deliberately
        # left out of the ON CONFLICT UPDATE SET below: a re-import (the
        # operator re-exporting as their research evolves) must not silently
        # revert a human's correction back to the heuristic's original
        # verdict. They are only ever set on first insert of a given
        # phrase+database. The counts returned on this result, below, always
        # reflect what the heuristic says about this run's rows regardless --
        # see the module docstring's "Design for correction" note.
        # `editorial` / `intent_labels` are, by contrast, a direct,
        # deterministic re-derivation of the Intent cell itself (no fuzzy
        # phrase heuristic involved), so they ARE refreshed on every import,
        # same as `qualifies`.
        conn.execute(
            "INSERT INTO keyword (phrase, volume, difficulty, intent, database, "
            "measured_at, qualifies, source, competitor_brand, segment_relevant, "
            "segment_relevant_reason, intent_labels, editorial) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(phrase, database) DO UPDATE SET "
            "volume=excluded.volume, difficulty=excluded.difficulty, "
            "intent=excluded.intent, measured_at=excluded.measured_at, "
            "qualifies=excluded.qualifies, source=excluded.source, "
            "competitor_brand=excluded.competitor_brand, "
            "intent_labels=excluded.intent_labels, editorial=excluded.editorial",
            (
                phrase, volume_val, difficulty, intent_val, _DATABASE,
                _MEASURED_AT, 1 if q else 0, _SOURCE, competitor,
                segment_relevant_flag, segment_reason, intent_labels_text,
                editorial_flag,
            ),
        )
        imported += 1
        if editorial_flag:
            editorial_count += 1
        else:
            non_editorial_count += 1
        if q:
            qualifying += 1
        else:
            non_qualifying += 1
            if difficulty is None or not (difficulty < MAX_DIFFICULTY):
                missed_difficulty += 1
            if volume_val is None or not (volume_val > MIN_VOLUME):
                missed_volume += 1

        if segment_reason is None:
            segment_relevant_count += 1
        else:
            segment_excluded_count += 1
            excluded_by_reason[segment_reason] = excluded_by_reason.get(segment_reason, 0) + 1
            excluded_volume_by_reason[segment_reason] = (
                excluded_volume_by_reason.get(segment_reason, 0) + (volume_val or 0)
            )

    conn.commit()
    return LoadBankResult(
        imported=imported,
        qualifying=qualifying,
        non_qualifying=non_qualifying,
        missed_difficulty=missed_difficulty,
        missed_volume=missed_volume,
        segment_relevant=segment_relevant_count,
        segment_excluded=segment_excluded_count,
        excluded_by_reason=excluded_by_reason,
        excluded_volume_by_reason=excluded_volume_by_reason,
        editorial=editorial_count,
        non_editorial=non_editorial_count,
        skipped=tuple(skipped),
    )


# =============================================================================
# Competitor brand detection (spec §5b "Competitor brand terms")
# =============================================================================

#: Sunreef's direct catamaran-brand rivals. A real Semrush export carries no
#: `competitor_brand` column (that was this module's own committed-CSV
#: convenience, still honoured if present -- see `load_bank`), so these names
#: are matched directly against the phrase instead.
COMPETITOR_BRANDS = (
    "Lagoon", "Leopard", "Aquila", "Fountaine Pajot", "Bali", "Nautitech",
    "Xquisite", "Privilege", "Outremer", "Catana", "HH Catamarans",
    "Gunboat", "Excess",
)

#: Brand names that are also ordinary English words (or, for "excess" /
#: "privilege" specifically, common enough outside the boating world) --
#: named directly in the change brief as a false-positive risk: "excess
#: weight catamaran" is about weight, not the Excess brand. For these two
#: only, a bare match is not enough: the token must sit immediately next to a
#: boat-context word or a number (a model, e.g. "excess 11", "privilege
#: 510") before it counts as a brand mention. Every other brand in the list
#: above is specific enough (a proper noun with no common-word reading in
#: this domain) to match unconditionally.
_AMBIGUOUS_BRAND_TOKENS = frozenset({"excess", "privilege"})

_BRAND_CONTEXT_TOKENS = frozenset({
    "catamaran", "catamarans", "yacht", "yachts", "sailboat", "sailboats",
    "boat", "boats", "multihull", "multihulls", "charter", "sailing",
    "brokerage", "cruiser", "cruisers",
})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower())


def detect_competitor_brand(phrase: str) -> bool:
    """True if `phrase` names one of `COMPETITOR_BRANDS`.

    Multi-word brands ("Fountaine Pajot", "HH Catamarans") match as an exact
    token subsequence, which is already specific enough not to false-positive
    on ordinary phrases. Single-word brands match on token equality (not
    substring -- "leopard" does not match "leopards"), except the two
    ambiguous ones (see `_AMBIGUOUS_BRAND_TOKENS`), which additionally
    require an adjacent boat-context token or a number.
    """
    tokens = _tokenize(phrase)
    for brand in COMPETITOR_BRANDS:
        brand_tokens = _tokenize(brand)
        n = len(brand_tokens)
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] != brand_tokens:
                continue
            if n == 1 and brand_tokens[0] in _AMBIGUOUS_BRAND_TOKENS:
                prev_tok = tokens[i - 1] if i > 0 else None
                next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
                context_ok = any(
                    t is not None and (t in _BRAND_CONTEXT_TOKENS or t.isdigit())
                    for t in (prev_tok, next_tok)
                )
                if not context_ok:
                    continue
            return True
    return False


# =============================================================================
# Selection (spec §5b)
# =============================================================================


def _angle_text(angle: dict | None) -> str:
    if not angle:
        return ""
    return " ".join(
        str(angle.get(k) or "")
        for k in ("title", "premise", "audience_value", "sunreef_relevance")
    )


def _relevance_score(angle_tokens: set[str], phrase: str) -> int:
    """A simple, deterministic token-overlap score -- no API call, no
    embedding, per spec §5b: "Keep this simple and deterministic."
    """
    return len(angle_tokens & set(_tokenize(phrase)))


def _ranked_eligible_keywords(
    conn: sqlite3.Connection, angle: dict | None, exclude_ids
) -> list[dict]:
    """Every eligible keyword, ranked deterministically against `angle`'s
    text: highest relevance score first, ties broken by volume (descending)
    and then phrase (ascending) so the order never depends on SQLite's row
    order or dict iteration order.

    Eligible means all four independent gates pass: `qualifies=1` (clears the
    §5b volume/difficulty thresholds), `segment_relevant=1` (is actually
    about Sunreef's segment, not a rug or a pharmacy benefit manager that
    happens to clear those thresholds), `editorial=1` (Semrush Intent
    includes Informational and excludes Transactional/Navigational --
    Commercial is retained), and `competitor_brand=0` (not a rival brand
    name, which needs an explicit human decision this task does not build).

    Long/medium/short all call this with the same `angle`, so they always get
    the *same* ranked list -- only how much of its prefix each format takes
    differs (`select_for_draft`). That is what makes medium/short's keywords
    a structural subset of long's, not just a usual-case coincidence.
    """
    rows = conn.execute(
        "SELECT * FROM keyword WHERE qualifies=1 AND segment_relevant=1 "
        "AND editorial=1 AND competitor_brand=0"
    ).fetchall()
    excluded = set(exclude_ids or ())
    angle_tokens = set(_tokenize(_angle_text(angle)))
    candidates = [dict(r) for r in rows if r["id"] not in excluded]
    candidates.sort(
        key=lambda row: (
            -_relevance_score(angle_tokens, row["phrase"]),
            -(row["volume"] or 0),
            row["phrase"],
        )
    )
    return candidates


def select_for_draft(
    conn: sqlite3.Connection, format: str, angle: dict | None, exclude_ids=()
) -> dict:
    """Primary + secondary keywords for one draft format (spec §5b).

    Only rows clearing all four gates are ever eligible -- `qualifies=1`,
    `segment_relevant=1`, `editorial=1`, `competitor_brand=0` (see
    `_ranked_eligible_keywords`) -- never relaxed, never substituted. If
    nothing is eligible, returns `{"primary": None, "secondary": []}` for
    every format, and the caller proceeds with no keywords rather than
    lowering the bar (spec §5b "When nothing qualifies").

    `exclude_ids` removes specific keyword ids from consideration entirely
    (e.g. one a human has explicitly rejected for this broker) -- an escape
    hatch, not the mechanism that keeps medium/short inside long's set; that
    guarantee comes from `_ranked_eligible_keywords` always producing the
    same ranked order regardless of format, with only the slice length
    varying by `FORMAT_KEYWORD_COUNTS[format]`.
    """
    if format not in FORMAT_KEYWORD_COUNTS:
        raise ValueError(f"unknown draft format: {format!r}")
    _primary_count, secondary_count = FORMAT_KEYWORD_COUNTS[format]
    ranked = _ranked_eligible_keywords(conn, angle, exclude_ids)
    if not ranked:
        return {"primary": None, "secondary": []}
    primary = ranked[0]
    secondary = ranked[1:1 + secondary_count]
    return {"primary": primary, "secondary": secondary}
