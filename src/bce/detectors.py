"""Pure detectors used by Stage 2 qualification (spec §5).

No network, no I/O — qualification logic is testable without crawling
anything.

**Input shapes.** Two different shapes are used here and mixing them up is a
real defect (a raw response body makes `width='150'` look like a 150ft vessel):

- `detect_max_length_ft`, `detect_sunreef_affinity` take **extracted text** —
  human-visible prose, no markup, no inline script. `visible_text()` derives it.
- `find_editorial_urls`, `detect_newsletter`, `detect_last_post_date` take
  **raw HTML**, because they read attributes (`href`, `input type=email`,
  `<time datetime>`). They strip `<script>`/`<style>` themselves.
"""
import re
from urllib.parse import urljoin, urlparse

from htmldate import find_date
from selectolax.parser import HTMLParser

_CODE_TAGS = ("script", "style", "noscript", "template")


def _parse_without_code(html: str) -> HTMLParser:
    tree = HTMLParser(html or "")
    tree.strip_tags(list(_CODE_TAGS))
    return tree


def visible_text(html: str) -> str:
    """Human-visible prose from an HTTP response body.

    Markup, inline `<script>` and `<style>` are removed, so numbers that only
    exist in attributes or JavaScript cannot be mistaken for prose (spec §4 —
    the >=60ft gate is read off what the broker actually says).
    """
    node = _parse_without_code(html).body
    if node is None:  # malformed markup with no body
        return ""
    return node.text(separator=" ")


def _markup_without_code(html: str) -> str:
    """Raw markup with `<script>`/`<style>` removed, attributes intact."""
    node = _parse_without_code(html).body
    return node.html if node is not None else ""


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


_NEWSLETTER_HINTS = ("newsletter", "mailing list", "email updates", "email list")
_NEWSLETTER_RE = re.compile(
    r"\b(?:"
    + "|".join(h.replace(" ", r"[\s\-_]+") for h in _NEWSLETTER_HINTS)
    + r")s?\b",
    re.IGNORECASE,
)
# "subscribe" on its own is not evidence of an email newsletter: it is also
# `store.subscribe(fn)`, "Subscribe to our YouTube channel", and privacy-policy
# boilerplate. It counts only alongside an email co-signal.
_SUBSCRIBE_RE = re.compile(r"\bsubscrib(?:e|ing|er|ers|ption|ptions)\b", re.IGNORECASE)
_EMAIL_INPUT_RE = re.compile(r"<input\b[^>]*type\s*=\s*['\"]?email", re.IGNORECASE)
_EMAIL_WORD_RE = re.compile(r"\b(?:e-?mail|inbox)\b", re.IGNORECASE)


def _evidence(source: str, at: int) -> str:
    start = max(0, at - _EVIDENCE_CHARS // 2)
    return source[start:start + _EVIDENCE_CHARS].strip()


def _form_evidence(markup: str) -> str | None:
    """Evidence text from a `<form>` whose own subtree carries both a
    subscribe mention and an email input, or None.

    Deliberately DOM-based, not a lazy tag-matching regex: a hand-written
    `<(form|section)\\b.*?</\\1>` pattern matches from an *outer* open tag to
    the first literal closing tag, so it spans everything nested inside —
    including an unrelated footer "Subscribe to our YouTube channel" and a
    distant contact-form input that merely share a broad `<section>`
    wrapper. `HTMLParser` gives each `<form>` node's own, correctly-nested
    subtree HTML, so a match here means the two signals genuinely live in
    the same form — not merely under the same broad container. Restricted
    to `<form>` (not `<section>`/`<div>`) because a form is a narrow,
    purpose-built container; a `<section>` routinely is not, which is
    exactly the shape that reopened this defect.

    Evidence is sliced from the form's own HTML, not the full-page markup:
    a match's offset is only meaningful within the string it was found in.
    """
    for node in HTMLParser(markup).css("form"):
        form_html = node.html or ""
        subscribe_match = _SUBSCRIBE_RE.search(form_html)
        if subscribe_match and _EMAIL_INPUT_RE.search(form_html):
            return _evidence(form_html, subscribe_match.start())
    return None


def detect_newsletter(html: str) -> tuple[bool, str]:
    """Does this broker run an email newsletter? (spec §4)

    A newsletter is a publishing channel in its own right, not a weaker
    substitute for a blog — it reaches an opted-in list directly. Because a
    newsletter alone qualifies a broker (spec §4 v0.5), a false positive costs
    an outreach slot on a channel that does not exist, so this is deliberately
    precision-first: an explicit newsletter/mailing-list phrase, or the word
    "subscribe" backed by a *local* email co-signal — the word "email"/
    "inbox" nearby, an `<input type="email">` in the same proximity window,
    or an `<input type="email">` inside the same `<form>` subtree (checked
    via the DOM, not a regex "enclosing block", so a `<form>`/`<section>`
    cannot be conflated with an unrelated container that happens to wrap
    both a decoy mention and a distant, unrelated input). An email input is
    near-universal (contact forms) and footers routinely carry a social
    "Subscribe", so the co-signal must be local to the match, not merely
    present anywhere on the page.
    """
    markup = _markup_without_code(html)

    match = _NEWSLETTER_RE.search(markup)
    if match is not None:
        return True, _evidence(markup, match.start())

    for m in _SUBSCRIBE_RE.finditer(markup):
        window_start = max(0, m.start() - _PROXIMITY_CHARS)
        window = markup[window_start:m.end() + _PROXIMITY_CHARS]
        if _EMAIL_WORD_RE.search(window) or _EMAIL_INPUT_RE.search(window):
            return True, _evidence(markup, m.start())

    evidence = _form_evidence(markup)
    if evidence is not None:
        return True, evidence

    return False, ""


def detect_last_post_date(html: str) -> str | None:
    """Publication date of an editorial page as `YYYY-MM-DD`, or None.

    Spec §4 qualifies an editorial section only when it was *updated within the
    last 12 months*, so a link to a journal is not enough — something has to
    have been published behind it. `extensive_search=False` keeps this to
    dates the page actually declares (metadata, `<time>`), rather than
    guessing from a footer copyright year.
    """
    if not html:
        return None
    try:
        return find_date(html, outputformat="%Y-%m-%d", extensive_search=False)
    except Exception:  # htmldate raises a variety of parse errors on junk input
        return None
