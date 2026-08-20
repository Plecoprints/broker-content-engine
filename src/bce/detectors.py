"""Pure detectors used by Stage 2 qualification (spec §5).

Every function here takes text and returns a value — no network, no I/O — so
qualification logic is testable without crawling anything.
"""
import re

_MIN_FT = 20
_MAX_FT = 400
_M_TO_FT = 3.28084

_FEET_RE = re.compile(r"(\d{2,3})\s*(?:ft\b|feet\b|foot\b|')", re.IGNORECASE)
_METRE_RE = re.compile(r"(\d{2,3})\s*(?:m\b|metre|meter)", re.IGNORECASE)


def detect_max_length_ft(text: str) -> int | None:
    """Largest plausible vessel length in feet, or None."""
    candidates: list[int] = []

    for raw in _FEET_RE.findall(text):
        candidates.append(int(raw))

    for raw in _METRE_RE.findall(text):
        candidates.append(round(int(raw) * _M_TO_FT))

    plausible = [c for c in candidates if _MIN_FT <= c <= _MAX_FT]
    return max(plausible) if plausible else None
