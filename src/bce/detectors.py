"""Pure detectors used by Stage 2 qualification (spec §5).

Every function here takes text and returns a value — no network, no I/O — so
qualification logic is testable without crawling anything.
"""
import re
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser

_MIN_FT = 20
_MAX_FT = 400
_M_TO_FT = 3.28084

_FEET_RE = re.compile(r"(?<![\d$£€])(\d{2,3})\s*(?:ft\b|feet\b|foot\b|')", re.IGNORECASE)
_METRE_RE = re.compile(r"(?<![\d$£€])(\d{2,3})\s*(?:m\b|metre|meter)", re.IGNORECASE)


def detect_max_length_ft(text: str) -> int | None:
    """Largest plausible vessel length in feet, or None."""
    candidates: list[int] = []

    for raw in _FEET_RE.findall(text):
        candidates.append(int(raw))

    for raw in _METRE_RE.findall(text):
        candidates.append(round(int(raw) * _M_TO_FT))

    plausible = [c for c in candidates if _MIN_FT <= c <= _MAX_FT]
    return max(plausible) if plausible else None


_SUNREEF_RE = re.compile(r"sunreef", re.IGNORECASE)
_LISTING_MARKERS = (
    "for sale", "price", "asking", "listing", "available now", "charter from",
)
_PROXIMITY_CHARS = 120
_EVIDENCE_CHARS = 160


def detect_sunreef_affinity(text: str) -> tuple[str, str]:
    """Publicly-observable Sunreef relationship signal (spec §4).

    Ordering only — must never gate pipeline behaviour or quality.
    """
    match = _SUNREEF_RE.search(text)
    if match is None:
        return "none", ""

    lowered = text.lower()
    for m in _SUNREEF_RE.finditer(text):
        window_start = max(0, m.start() - _PROXIMITY_CHARS)
        window = lowered[window_start:m.end() + _PROXIMITY_CHARS]
        if any(marker in window for marker in _LISTING_MARKERS):
            # Compute evidence from the match that triggered lists_inventory
            start = max(0, m.start() - _EVIDENCE_CHARS // 2)
            evidence = text[start:start + _EVIDENCE_CHARS].strip()
            return "lists_inventory", evidence

    # No listing marker found; use evidence from first mention
    start = max(0, match.start() - _EVIDENCE_CHARS // 2)
    evidence = text[start:start + _EVIDENCE_CHARS].strip()
    return "mentions", evidence


_EDITORIAL_HINTS = (
    "blog", "news", "journal", "insights", "article", "stories", "guides",
)
_EDITORIAL_RE = re.compile(
    r"\b(?:" + "|".join(_EDITORIAL_HINTS) + r")s?\b", re.IGNORECASE
)


def find_editorial_urls(html: str, base_url: str) -> list[str]:
    """Same-host links that look like editorial sections (spec §5 Stage 2)."""
    base_host = urlparse(base_url).netloc
    found: list[str] = []

    for node in HTMLParser(html).css("a"):
        href = node.attributes.get("href")
        if not href:
            continue

        anchor = node.text() or ""
        haystack = f"{href} {anchor}"
        if not _EDITORIAL_RE.search(haystack):
            continue

        absolute = urljoin(base_url, href)
        if urlparse(absolute).netloc != base_host:
            continue
        if absolute not in found:
            found.append(absolute)

    return found
