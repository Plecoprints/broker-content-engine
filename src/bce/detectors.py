"""Pure detectors used by Stage 2 qualification (spec §5).

No network, no I/O — qualification logic is testable without crawling
anything.

**Input shapes.** Two different shapes are used here and mixing them up is a
real defect (a raw response body makes `width='150'` look like a 150ft vessel):

- `detect_max_length_ft`, `detect_sunreef_affinity` take **extracted text** —
  human-visible prose, no markup, no inline script. `visible_text()` derives it.
- `find_editorial_urls`, `find_post_links`, `detect_newsletter`,
  `detect_last_post_date` take **raw HTML**, because they read attributes
  (`href`, `input type=email`, `<time datetime>`). They strip
  `<script>`/`<style>` themselves.

`find_post_links` is the one function here Stage 3 rather than Stage 2 needs
(spec §5 Stage 3); it lives beside `find_editorial_urls` because it is the
second half of the same walk — section, then the posts behind it.
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


_YEAR_SEGMENT_RE = re.compile(r"^(?:19|20)\d{2}$")
_NON_PAGE_SCHEMES = ("mailto:", "tel:", "javascript:", "data:")

#: Page furniture. Links here are site chrome, not editorial content, and the
#: distinction is structural rather than a list of paths to ignore.
_CHROME_TAGS = ("nav", "header", "footer", "aside")

#: Distinct same-host content links that make a page an *index* rather than an
#: article. Three, because a journal index shows at least three posts, while a
#: single long-form piece rarely carries three distinct in-body links to other
#: pages of the same site. Below three the depth/date rule still applies, and the
#: `MIN_ARTICLE_CHARS` floor covers what is left: a two-card index extracts to
#: roughly 325 chars, well under the 600-char floor.
MIN_INDEX_LINKS = 3


def _path_segments(url: str) -> list[str]:
    return [seg for seg in urlparse(url).path.split("/") if seg]


def _content_region(html: str):
    """The page's editorial region: `<main>` if it declares one, else the body
    with nav/header/footer/aside removed. Returns None for unusable markup."""
    tree = HTMLParser(html or "")
    tree.strip_tags(list(_CHROME_TAGS))
    return tree.css_first("main") or tree.body


def _candidate_links(html: str, index_url: str, exclude: list[str] | None) -> list[str]:
    """Distinct same-host, fetchable content-region links, in document order."""
    region = _content_region(html)
    if region is None:
        return []

    base_host = urlparse(index_url).netloc
    skip = {index_url.rstrip("/")}
    for url in exclude or []:
        skip.add(url.rstrip("/"))

    found: list[str] = []
    for node in region.css("a"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        if href.lower().startswith(_NON_PAGE_SCHEMES):
            continue

        absolute = urljoin(index_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or parsed.netloc != base_host:
            continue
        absolute = parsed._replace(fragment="").geturl()
        if absolute.rstrip("/") in skip:
            continue
        if absolute not in found:
            found.append(absolute)

    return found


def looks_like_index(html: str, index_url: str, exclude: list[str] | None = None) -> bool:
    """Is this page a list of posts rather than a post?

    **Structural, not textual, and independent of path shape.** A page carrying
    MIN_INDEX_LINKS or more distinct same-host links in its content region is an
    index. That holds for WordPress's default `/%postname%/` permalinks, where a
    `/journal` index links to `/why-beam-matters` — neither deeper than the index
    nor dated, so a path-shape rule sees no posts at all and the index sails
    through as an "article".

    It cannot be defeated by rewriting URLs, because it reads how many places the
    page sends you rather than what those places are called. A length test cannot
    stand in for it: teaser text scales with card count, so a busy index clears
    any character floor precisely when it is least like an article.
    """
    return len(_candidate_links(html, index_url, exclude)) >= MIN_INDEX_LINKS


def find_post_links(html: str, index_url: str, exclude: list[str] | None = None) -> list[str]:
    """Same-host links on an editorial *index* that look like individual posts.

    `find_editorial_urls` returns section pages — `/journal`, `/news`, `/blog`.
    Handing those straight to an article extractor profiles the index: trafilatura
    on a journal index yields teaser fragments, not an article body, and the
    statistics derived from it describe the site's card layout rather than how the
    broker writes (spec §5 Stage 3, §10.3 *Tailored*). This is the second hop.

    Candidates are same-host, fetchable links in the **content region** — `<main>`
    when the page declares one, otherwise the body with nav/header/footer/aside
    stripped — excluding the index itself and the editorial section URLs already
    known. Nothing is classified by a model.

    Which candidates count as posts depends on what the page is:

    - **An index** (`looks_like_index`): every candidate. This is what finds flat
      `/%postname%/` permalinks, which no path-shape rule can see.
    - **Anything else**: only candidates that are deeper than the index
      (`/journal/why-beam-matters`) or carry a date segment (`/2026/03/berthing`),
      so a long-form page that happens to link to `/contact` in its body is not
      mistaken for a listing.

    Trade accepted: on a page with no `<main>` and no `<nav>`, chrome links are
    indistinguishable from cards and may be fetched. They are same-host pages that
    fail the `MIN_ARTICLE_CHARS` floor, so they cost a bounded number of requests
    and never reach the statistics.

    Document order is preserved and duplicates dropped, so the caller's fetch
    budget is spent on the most prominent posts — normally the newest.
    """
    candidates = _candidate_links(html, index_url, exclude)
    if len(candidates) >= MIN_INDEX_LINKS:
        return candidates

    index_depth = len(_path_segments(index_url))
    posts: list[str] = []
    for absolute in candidates:
        segments = _path_segments(absolute)
        deeper = len(segments) > index_depth
        dated = any(_YEAR_SEGMENT_RE.match(seg) for seg in segments)
        if deeper or dated:
            posts.append(absolute)
    return posts


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
