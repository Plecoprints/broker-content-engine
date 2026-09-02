"""No-product-claims gate (spec §10.4 as revised 2026-09-02, §10.9).

**What this enforces, and why it is a refusal rather than a check.** §10.4
originally required that any claim about a Sunreef vessel be *verifiable
against official Sunreef material*. There is no such material in machine-
readable form, and neither a human reviewer nor a judge model substitutes for
one: asking a model to check another model's claims about Sunreef vessels
produces two guesses, correlated where they share a lineage. So the rule was
inverted. A draft may make **no specific factual claim about a named Sunreef
vessel at all** -- no dimension, capacity, performance figure or
certification. Blocking a claim is arithmetic; verifying one is a research
project.

This costs nothing editorially. §5b's intent rule and `bce.draft._SYSTEM`
("not an advertisement for any yacht brand") already push every angle toward
category content -- how a catamaran differs from a monohull, what ownership
costs, how solar propulsion actually performs -- none of which needs a
Sunreef spec sheet.

**Why it is scoped to *named vessels*.** The gate fires on a model
designation ("Sunreef 80 Eco", "Ultima 111"), never on the bare company name.
"Sunreef builds catamarans in Gdansk" near "a 60ft catamaran typically costs"
is ordinary category prose and must not be blocked; §10.4's exposure is
specifically a figure the reader will take as a specification of a boat they
could buy.

**Why proximity rather than sentence structure.** A claim routinely spans a
sentence boundary -- "The Sunreef 80 Eco is remarkable. It carries 46 m2 of
solar." -- so a per-sentence test would miss the common case. A character
window catches it, is trivial to explain to a reviewer, and errs toward
blocking. That direction is deliberate: this gate guards the one risk §12
rates Critical, and a false reject costs a regeneration while a false accept
costs a fabricated specification on a partner's website.

**Known limitation, recorded rather than hidden.** Prose that describes a
vessel without designating it -- "their largest sailing catamaran carries 46
m2 of solar" -- evades this gate, as does any spec unit not in
`_SPEC_UNIT_PATTERN`. The gate is a floor, not a proof. It is also why §10.9
keeps operator sampling at 100% for the first pilot run.
"""
import re

#: Characters between a named vessel and a specification for the two to count
#: as one claim. Roughly two sentences: wide enough for the pronoun
#: continuation above, narrow enough that an unrelated mention elsewhere in a
#: 2,300-word pillar does not collide with it.
PROXIMITY_CHARS = 300

#: Sunreef range words that appear alongside a number in a model designation.
#: Matched either side of the number, since both orders are in real use
#: ("Sunreef 80 Eco", "Sunreef Power 80").
_RANGE_WORDS = ("Eco", "Power", "Supreme", "Ultima", "Explorer", "Zero")

_RANGE = "|".join(_RANGE_WORDS)

#: A *named* Sunreef vessel. Three forms, deliberately not an enumerated model
#: list -- Sunreef releases new models, and a gate that needs updating every
#: time one ships is a gate that silently stops working.
#:
#:   1. `Sunreef [Range] <number>[M] [Range]` -- the common case
#:   2. `Sunreef Zero Cat` -- named without a number
#:   3. `<number> Eco` / `Ultima <number>` -- the shorthand a draft slips into
#:      after introducing the boat. Scoped to range words distinctive enough
#:      that a bare number cannot trigger it.
VESSEL_PATTERN = re.compile(
    r"""(?:
          Sunreef \s+ (?:(?:%(range)s)\s+)? \d{2,3} (?:\s*M)? (?:\s+(?:%(range)s))?
        | Sunreef \s+ Zero \s+ Cat
        | Ultima \s+ \d{2,3}
        | \d{2,3} \s+ Eco \b
    )""" % {"range": _RANGE},
    re.IGNORECASE | re.VERBOSE,
)

#: Units that make a number a *specification* rather than ordinary prose. Bare
#: numbers are not enough: "building catamarans for 20 years" is a company
#: fact, not a vessel spec, and §10.4 is about vessels. Units that are also
#: common English words ("in" for inches) are omitted -- the false-positive
#: cost is not worth the coverage.
_SPEC_UNIT_PATTERN = r"""(?:
      ft|feet|foot|'|"
    | m|metres?|meters?|cm|mm|inch(?:es)?
    | m2|m²|sq\.?\s?m|square\s+met(?:re|er)s?|sq\.?\s?ft|square\s+feet
    | t|tonnes?|tons?|kg|lbs?
    | hp|bhp|kW|kWp|MW
    | kWh|MWh|Ah
    | kn|kts?|knots?|mph|km/h
    | nm|nautical\s+miles?
    | l|litres?|liters?|gal(?:lons?)?
)"""

#: number + spec unit, e.g. "24.4 m", "46 m2", "1,200 nm", "80'"
#:
#: Terminated with `(?!\w)` rather than `\b`: a word boundary cannot be
#: asserted after a non-word unit like the foot mark in `78'`, so `\b` silently
#: failed to match exactly the shorthand a yacht article is most likely to use.
#: The lookahead also keeps the short units honest -- `m` is tried before
#: `metres`, matches, then fails the lookahead on the `e` and backtracks into
#: the longer alternative.
SPEC_QUANTITY_PATTERN = re.compile(
    r"\b\d[\d,.]*\s*" + _SPEC_UNIT_PATTERN + r"(?!\w)",
    re.IGNORECASE | re.VERBOSE,
)

#: number + accommodation noun. A count with no unit, but unmistakably a
#: specification of a particular boat.
BERTH_PATTERN = re.compile(
    r"\b\d{1,2}\s+(?:berths?|cabins?|guests?|crew|passengers?|staterooms?|heads)\b",
    re.IGNORECASE,
)

#: Class, flag and standards bodies. A certification attached to a named
#: vessel is the §10.4 case that would embarrass Sunreef most, because a
#: broker's reader may act on it.
CERTIFICATION_PATTERN = re.compile(
    r"""(?:
          CE \s* (?:category \s*)? [ABC]\b
        | RINA | MCA | ABS | DNV(?:-GL)? | Bureau \s+ Veritas
        | Lloyd'?s (?:\s+Register)?
        | SOLAS | LY3 | Red \s+ Ensign
        | ISO \s* \d{3,5}
        | Polish \s+ Register \s+ of \s+ Shipping
    )""",
    re.IGNORECASE | re.VERBOSE,
)

_CLAIM_PATTERNS = (
    ("specification", SPEC_QUANTITY_PATTERN),
    ("accommodation", BERTH_PATTERN),
    ("certification", CERTIFICATION_PATTERN),
)


def _mask(text: str, spans) -> str:
    """Blank out `spans` while preserving every offset.

    A model designation contains digits -- "Sunreef 43M" reads as 43 metres to
    a unit matcher -- so vessel matches are masked before specifications are
    looked for. Replacing with spaces rather than deleting keeps every
    remaining match's index valid for the proximity test and the snippet.
    """
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def find_product_claims(body: str) -> list[dict]:
    """Every specification found within `PROXIMITY_CHARS` of a named vessel.

    Each entry carries the vessel text, the claim text, the claim's kind, and
    a snippet of surrounding prose -- because a gate that reports only "failed"
    cannot be acted on. A human (or a redraft prompt) needs to see what
    tripped it.

    Ordered by where the claim appears, so a reviewer reads them in the order
    they occur in the draft.
    """
    if not body:
        return []
    vessels = [(m.start(), m.end(), m.group(0)) for m in VESSEL_PATTERN.finditer(body)]
    if not vessels:
        return []

    masked = _mask(body, [(s, e) for s, e, _ in vessels])
    found: list[dict] = []
    for kind, pattern in _CLAIM_PATTERNS:
        for match in pattern.finditer(masked):
            near = [
                (vs, ve, vtext) for vs, ve, vtext in vessels
                if _distance(match.start(), match.end(), vs, ve) <= PROXIMITY_CHARS
            ]
            if not near:
                continue
            vs, ve, vtext = min(
                near, key=lambda v: _distance(match.start(), match.end(), v[0], v[1])
            )
            lo = max(0, min(match.start(), vs) - 40)
            hi = min(len(body), max(match.end(), ve) + 40)
            found.append({
                "kind": kind,
                "vessel": " ".join(vtext.split()),
                "claim": " ".join(match.group(0).split()),
                "snippet": " ".join(body[lo:hi].split()),
            })
    found.sort(key=lambda c: body.find(c["claim"]) if c["claim"] in body else 0)
    return found


def _distance(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    """Gap between two spans; 0 when they touch or overlap."""
    if a_end <= b_start:
        return b_start - a_end
    if b_end <= a_start:
        return a_start - b_end
    return 0


def check_no_product_claims(body: str) -> dict:
    """The gate (spec §10.4, §10.9). `passes` is False if any claim was found.

    Mirrors `bce.originality`'s gate shape -- a dict with `passes` plus the
    evidence behind the verdict -- so `run_gates` combines it the same way as
    the other three and the draft row records what it collided with.
    """
    claims = find_product_claims(body)
    return {"passes": not claims, "claims": claims}
