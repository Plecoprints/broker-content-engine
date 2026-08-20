# Shortlist Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data layer and Stages 1–2 of the Broker Partner Content Engine, producing a vetted broker shortlist in SQLite.

**Architecture:** A Python package (`src/bce/`) with a SQLite store as single source of truth. A robots-aware, rate-limited fetcher feeds pure-function detectors (length criterion, editorial section, Sunreef affinity) which a qualification orchestrator composes into a verdict per broker. A CLI drives the stages. Detectors are pure string→value functions so they test without network.

**Tech Stack:** Python 3.11.9, sqlite3 (stdlib), httpx, selectolax, htmldate, pytest

**Spec:** `docs/superpowers/specs/2026-08-20-broker-partner-content-design.md`

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include these.

- `robots.txt` respected. Rate limit **≥2s per domain**. Identifying User-Agent with a contact URL. (spec §10.2)
- No login-gated or paywalled content. Public pages only. (spec §2)
- Never store full article text — derived features and short quotes only. (spec §10.3)
- SQLite is the single source of truth for state. (spec §7)
- Hard cap **50** brokers, default working set **20**. (spec §6)
- No tiered service. `sunreef_affinity` orders the queue only; it never changes pipeline behaviour. (spec §2, §4)
- Qualifying broker: multihulls/yachts **≥60ft**, in Sunreef markets, editorial updated within 12 months. (spec §4)
- Python 3.11.9. Contact URL for User-Agent comes from env `BCE_CONTACT_URL`, default `https://www.sunreef-yachts.com/` — **confirm the correct public contact URL with Luis before first live crawl.**

---

### Task 1: Project scaffold

**Files:**
- Create: `broker-content-engine/pyproject.toml`
- Create: `broker-content-engine/.gitignore`
- Create: `broker-content-engine/src/bce/__init__.py`
- Create: `broker-content-engine/tests/__init__.py`
- Test: `broker-content-engine/tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: importable package `bce` with `bce.__version__: str`

- [ ] **Step 1: Write the failing test**

`tests/test_smoke.py`:
```python
def test_package_imports_and_has_version():
    import bce
    assert isinstance(bce.__version__, str)
    assert bce.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd broker-content-engine && python3 -m pytest tests/test_smoke.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce'`

- [ ] **Step 3: Write minimal implementation**

`pyproject.toml`:
```toml
[project]
name = "bce"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "httpx>=0.27,<1.0",
    "selectolax>=0.3.21,<0.4",
    "htmldate>=1.9,<2.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0,<9.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

`src/bce/__init__.py`:
```python
__version__ = "0.1.0"
```

`.gitignore`:
```
__pycache__/
*.pyc
.venv/
*.db
.pytest_cache/
*.egg-info/
```

`tests/__init__.py`: empty file.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest tests/ -v`
Expected: PASS, 1 test

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore src tests
git commit -m "feat: project scaffold with bce package"
```

---

### Task 2: SQLite schema and connection

**Files:**
- Create: `broker-content-engine/src/bce/db.py`
- Test: `broker-content-engine/tests/test_db.py`

**Interfaces:**
- Consumes: `bce` package from Task 1
- Produces:
  - `connect(path: str = "bce.db") -> sqlite3.Connection` — row_factory set to `sqlite3.Row`, foreign keys ON
  - `init_schema(conn: sqlite3.Connection) -> None` — idempotent
  - `SCHEMA_TABLES: tuple[str, ...]` = `("broker", "voice_profile", "angle", "draft", "outcome")`

- [ ] **Step 1: Write the failing test**

`tests/test_db.py`:
```python
import sqlite3
from bce import db


def test_init_schema_creates_all_tables():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r["name"] for r in rows}
    for table in db.SCHEMA_TABLES:
        assert table in names


def test_init_schema_is_idempotent():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    db.init_schema(conn)
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='broker'"
    ).fetchone()["c"]
    assert count == 1


def test_broker_affinity_constraint_rejects_unknown_value():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    try:
        conn.execute(
            "INSERT INTO broker (name, domain, source, sunreef_affinity) "
            "VALUES ('X', 'x.com', 'manual', 'bogus')"
        )
        raised = False
    except sqlite3.IntegrityError:
        raised = True
    assert raised


def test_rows_are_mappings():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO broker (name, domain, source) VALUES ('Acme', 'acme.com', 'manual')"
    )
    row = conn.execute("SELECT name FROM broker").fetchone()
    assert row["name"] == "Acme"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'db' from 'bce'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/db.py`:
```python
"""SQLite store — single source of truth for pipeline state (spec §7, §8)."""
import sqlite3

SCHEMA_TABLES = ("broker", "voice_profile", "angle", "draft", "outcome")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS broker (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    domain            TEXT NOT NULL UNIQUE,
    region            TEXT,
    segment_evidence  TEXT,
    source            TEXT NOT NULL CHECK (source IN ('discovered', 'manual')),
    sunreef_affinity  TEXT NOT NULL DEFAULT 'unknown'
                      CHECK (sunreef_affinity IN
                             ('none', 'mentions', 'lists_inventory', 'unknown')),
    affinity_evidence TEXT,
    qualified         INTEGER,
    qualified_reason  TEXT,
    robots_allowed    INTEGER,
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS voice_profile (
    broker_id          INTEGER PRIMARY KEY REFERENCES broker(id),
    register           TEXT,
    avg_sentence_len   REAL,
    typical_word_count INTEGER,
    structure_pattern  TEXT,
    vocabulary_markers TEXT,
    themes             TEXT,
    audience_signal    TEXT,
    sample_quotes      TEXT,
    analyzed_at        TEXT
);

CREATE TABLE IF NOT EXISTS angle (
    id               INTEGER PRIMARY KEY,
    broker_id        INTEGER NOT NULL REFERENCES broker(id),
    title            TEXT NOT NULL,
    premise          TEXT,
    audience_value   TEXT,
    sunreef_relevance TEXT,
    score            REAL,
    rejected_reason  TEXT
);

CREATE TABLE IF NOT EXISTS draft (
    id                            INTEGER PRIMARY KEY,
    angle_id                      INTEGER NOT NULL REFERENCES angle(id),
    body_md                       TEXT NOT NULL,
    word_count                    INTEGER,
    sunreef_mentions              INTEGER,
    passes_editorial_value_test   INTEGER,
    status                        TEXT NOT NULL DEFAULT 'pending_review'
                                  CHECK (status IN ('pending_review', 'approved',
                                         'rejected', 'sent', 'published', 'declined')),
    reviewed_by                   TEXT,
    reviewed_at                   TEXT,
    reviewer_edits                TEXT
);

CREATE TABLE IF NOT EXISTS outcome (
    draft_id          INTEGER PRIMARY KEY REFERENCES draft(id),
    sent_at           TEXT,
    response          TEXT,
    published_url     TEXT,
    utm_campaign      TEXT,
    referral_sessions INTEGER,
    inquiries         INTEGER
);
"""


def connect(path: str = "bce.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: PASS, 4 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/db.py tests/test_db.py
git commit -m "feat: SQLite schema with affinity and status constraints"
```

---

### Task 3: Yacht length detector

**Files:**
- Create: `broker-content-engine/src/bce/detectors.py`
- Test: `broker-content-engine/tests/test_detectors_length.py`

**Interfaces:**
- Consumes: nothing (pure function)
- Produces: `detect_max_length_ft(text: str) -> int | None` — largest plausible vessel length in feet found in `text`, or `None`. Metres converted at 3.28084 and rounded. Values outside 20–400 ft ignored.

- [ ] **Step 1: Write the failing test**

`tests/test_detectors_length.py`:
```python
import pytest
from bce.detectors import detect_max_length_ft


@pytest.mark.parametrize("text,expected", [
    ("Sunreef 80 Eco, 80 ft of luxury", 80),
    ("A 72ft catamaran", 72),
    ("Length overall: 68'", 68),
    ("24 m sailing catamaran", 79),          # 24 * 3.28084 = 78.7 -> 79
    ("22 meters of deck space", 72),
    ("Our fleet ranges from 45 ft to 90 ft", 90),
    ("no numbers here", None),
    ("Built in 1998, price 1200000", None),  # year/price must not match
    ("A 12 ft dinghy", None),                # below 20ft floor
    ("A 500 ft ship", None),                 # above 400ft ceiling
])
def test_detect_max_length_ft(text, expected):
    assert detect_max_length_ft(text) == expected


def test_prefers_largest_when_mixed_units():
    # 30m = 98ft beats the 60ft mention
    assert detect_max_length_ft("60 ft tender aboard a 30 m yacht") == 98
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detectors_length.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce.detectors'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/detectors.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detectors_length.py -v`
Expected: PASS, 11 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/detectors.py tests/test_detectors_length.py
git commit -m "feat: vessel length detector with unit conversion and bounds"
```

---

### Task 4: Sunreef affinity detector

**Files:**
- Modify: `broker-content-engine/src/bce/detectors.py`
- Test: `broker-content-engine/tests/test_detectors_affinity.py`

**Interfaces:**
- Consumes: `bce.detectors` from Task 3
- Produces: `detect_sunreef_affinity(text: str) -> tuple[str, str]` — returns `(level, evidence)` where level ∈ `{"none", "mentions", "lists_inventory"}` and evidence is a short quoted snippet (≤160 chars) or `""`. `lists_inventory` requires a Sunreef mention within 120 characters of a listing marker (`for sale`, `price`, `asking`, `listing`, `available now`, `charter from`).

**Spec constraint:** affinity is for queue ordering only (§4). This function must not be referenced by any code path that changes pipeline behaviour.

- [ ] **Step 1: Write the failing test**

`tests/test_detectors_affinity.py`:
```python
from bce.detectors import detect_sunreef_affinity


def test_no_mention_returns_none_level():
    level, evidence = detect_sunreef_affinity("We broker fine catamarans.")
    assert level == "none"
    assert evidence == ""


def test_bare_mention_returns_mentions():
    level, evidence = detect_sunreef_affinity(
        "We admire what Sunreef has done for luxury multihulls."
    )
    assert level == "mentions"
    assert "Sunreef" in evidence


def test_mention_near_listing_marker_returns_lists_inventory():
    level, evidence = detect_sunreef_affinity(
        "Sunreef 80 Eco — price on application. Contact our team."
    )
    assert level == "lists_inventory"
    assert "Sunreef" in evidence


def test_distant_listing_marker_does_not_upgrade():
    text = "Sunreef is a builder we respect. " + ("filler " * 40) + "Boats for sale."
    level, _ = detect_sunreef_affinity(text)
    assert level == "mentions"


def test_case_insensitive():
    level, _ = detect_sunreef_affinity("SUNREEF 60 available now")
    assert level == "lists_inventory"


def test_evidence_is_capped():
    level, evidence = detect_sunreef_affinity("Sunreef " + ("x" * 500))
    assert level == "mentions"
    assert len(evidence) <= 160
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detectors_affinity.py -v`
Expected: FAIL with `ImportError: cannot import name 'detect_sunreef_affinity'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/bce/detectors.py`:
```python
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

    start = max(0, match.start() - _EVIDENCE_CHARS // 2)
    evidence = text[start:start + _EVIDENCE_CHARS].strip()

    lowered = text.lower()
    for m in _SUNREEF_RE.finditer(text):
        window_start = max(0, m.start() - _PROXIMITY_CHARS)
        window = lowered[window_start:m.end() + _PROXIMITY_CHARS]
        if any(marker in window for marker in _LISTING_MARKERS):
            return "lists_inventory", evidence

    return "mentions", evidence
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detectors_affinity.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/detectors.py tests/test_detectors_affinity.py
git commit -m "feat: Sunreef affinity detector for queue ordering"
```

---

### Task 5: Editorial section detector

**Files:**
- Modify: `broker-content-engine/src/bce/detectors.py`
- Test: `broker-content-engine/tests/test_detectors_editorial.py`

**Interfaces:**
- Consumes: `bce.detectors` from Task 4, `selectolax`
- Produces: `find_editorial_urls(html: str, base_url: str) -> list[str]` — absolute URLs of links whose href or anchor text suggests editorial content (`blog`, `news`, `journal`, `insights`, `articles`, `stories`, `guides`). Deduplicated, order preserved, same-host only.

- [ ] **Step 1: Write the failing test**

`tests/test_detectors_editorial.py`:
```python
from bce.detectors import find_editorial_urls


def test_finds_blog_link_and_absolutizes():
    html = '<a href="/blog">Our Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/blog"]


def test_matches_anchor_text_when_href_is_opaque():
    html = '<a href="/p/12">Latest News</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/p/12"]


def test_ignores_offsite_links():
    html = '<a href="https://other.com/blog">Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


def test_ignores_non_editorial_links():
    html = '<a href="/contact">Contact</a><a href="/fleet">Our Fleet</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


def test_deduplicates_preserving_order():
    html = '<a href="/journal">Journal</a><a href="/news">News</a><a href="/journal">J</a>'
    assert find_editorial_urls(html, "https://acme.com") == [
        "https://acme.com/journal",
        "https://acme.com/news",
    ]


def test_handles_absolute_same_host():
    html = '<a href="https://acme.com/insights">Insights</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/insights"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_detectors_editorial.py -v`
Expected: FAIL with `ImportError: cannot import name 'find_editorial_urls'`

- [ ] **Step 3: Write minimal implementation**

Add to the top imports of `src/bce/detectors.py`:
```python
from urllib.parse import urljoin, urlparse

from selectolax.parser import HTMLParser
```

Append to `src/bce/detectors.py`:
```python
_EDITORIAL_HINTS = (
    "blog", "news", "journal", "insights", "article", "stories", "guides",
)


def find_editorial_urls(html: str, base_url: str) -> list[str]:
    """Same-host links that look like editorial sections (spec §5 Stage 2)."""
    base_host = urlparse(base_url).netloc
    found: list[str] = []

    for node in HTMLParser(html).css("a"):
        href = node.attributes.get("href")
        if not href:
            continue

        anchor = (node.text() or "").lower()
        haystack = f"{href.lower()} {anchor}"
        if not any(hint in haystack for hint in _EDITORIAL_HINTS):
            continue

        absolute = urljoin(base_url, href)
        if urlparse(absolute).netloc != base_host:
            continue
        if absolute not in found:
            found.append(absolute)

    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_detectors_editorial.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/detectors.py tests/test_detectors_editorial.py
git commit -m "feat: editorial section link detector"
```

---

### Task 5b: Newsletter detector

Added after review of Task 5 surfaced that `newsletter` was being matched as a blog hint. Separating them was the fix; this task makes the newsletter its own tracked channel, per spec §4 (v0.5).

**Files:**
- Modify: `broker-content-engine/src/bce/detectors.py`
- Modify: `broker-content-engine/src/bce/db.py`
- Test: `broker-content-engine/tests/test_detectors_newsletter.py`
- Test: `broker-content-engine/tests/test_db.py` (add one column-presence test)

**Interfaces:**
- Consumes: `bce.detectors` (`_EVIDENCE_CHARS` from Task 4), `bce.db` schema from Task 2
- Produces:
  - `detect_newsletter(html: str) -> tuple[bool, str]` — `(present, evidence)`; evidence capped at `_EVIDENCE_CHARS` (160), `""` when absent
  - three new `broker` columns: `has_editorial INTEGER`, `has_newsletter INTEGER`, `newsletter_evidence TEXT`

Searches raw HTML rather than extracted text, deliberately: signup markup (`class="newsletter-signup"`, `<input type="email">` wrappers) is itself evidence of a newsletter, so attribute matches are signal here rather than noise.

- [ ] **Step 1: Write the failing test**

`tests/test_detectors_newsletter.py`:
```python
from bce.detectors import detect_newsletter, find_editorial_urls


def test_detects_newsletter_signup():
    present, evidence = detect_newsletter("Sign up for our newsletter below.")
    assert present is True
    assert "newsletter" in evidence.lower()


def test_detects_subscribe_wording():
    present, _ = detect_newsletter("Subscribe to receive new listings.")
    assert present is True


def test_detects_mailing_list_across_whitespace():
    present, _ = detect_newsletter("Join our mailing\n    list today.")
    assert present is True


def test_detects_signup_markup():
    present, _ = detect_newsletter('<div class="newsletter-signup"></div>')
    assert present is True


def test_absent_returns_false_and_empty_evidence():
    present, evidence = detect_newsletter("We sell fine catamarans.")
    assert present is False
    assert evidence == ""


def test_case_insensitive_and_plural():
    assert detect_newsletter("NEWSLETTERS")[0] is True


def test_evidence_is_capped():
    present, evidence = detect_newsletter("newsletter " + "x" * 500)
    assert present is True
    assert len(evidence) <= 160


def test_newsletter_is_not_an_editorial_url():
    """Guards Task 5's fix: /newsletter must not count as an editorial section,
    while still being detected as a newsletter channel."""
    html = '<a href="/newsletter">Newsletter</a>'
    assert find_editorial_urls(html, "https://acme.com") == []
    assert detect_newsletter(html)[0] is True
```

Add to `tests/test_db.py`:
```python
def test_broker_has_channel_columns():
    conn = db.connect(":memory:")
    db.init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(broker)")}
    assert {"has_editorial", "has_newsletter", "newsletter_evidence"} <= cols
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_detectors_newsletter.py tests/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'detect_newsletter'`, and the column test fails on the missing columns.

- [ ] **Step 3: Write minimal implementation**

Append to `src/bce/detectors.py`:
```python
_NEWSLETTER_HINTS = ("newsletter", "subscribe", "mailing list", "email updates")
_NEWSLETTER_RE = re.compile(
    r"\b(?:"
    + "|".join(h.replace(" ", r"[\s\-_]+") for h in _NEWSLETTER_HINTS)
    + r")s?\b",
    re.IGNORECASE,
)


def detect_newsletter(html: str) -> tuple[bool, str]:
    """Does this broker run an email newsletter? (spec §4)

    A newsletter is a publishing channel in its own right, not a weaker
    substitute for a blog — it reaches an opted-in list directly.
    """
    match = _NEWSLETTER_RE.search(html)
    if match is None:
        return False, ""
    start = max(0, match.start() - _EVIDENCE_CHARS // 2)
    return True, html[start:start + _EVIDENCE_CHARS].strip()
```

In `src/bce/db.py`, add three columns to the `broker` table DDL, immediately after `affinity_evidence`:
```sql
    has_editorial     INTEGER,
    has_newsletter    INTEGER,
    newsletter_evidence TEXT,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — all prior tests plus 8 new newsletter tests and 1 new column test.

- [ ] **Step 5: Commit**

```bash
git add src/bce/detectors.py src/bce/db.py tests/test_detectors_newsletter.py tests/test_db.py
git commit -m "feat: newsletter channel detector and broker channel columns"
```

---

### Task 6: Robots-aware rate-limited fetcher

**Files:**
- Create: `broker-content-engine/src/bce/fetch.py`
- Test: `broker-content-engine/tests/test_fetch.py`

**Interfaces:**
- Consumes: `httpx`, stdlib `urllib.robotparser`
- Produces:
  - `USER_AGENT: str` — built from env `BCE_CONTACT_URL`
  - `class Fetcher(min_delay: float = 2.0, client: httpx.Client | None = None)`
  - `Fetcher.robots_allows(url: str) -> bool` — caches per host
  - `Fetcher.get(url: str) -> str | None` — returns body text, or `None` when disallowed or non-200. Sleeps to enforce `min_delay` per host.

**Spec constraint:** ≥2s per domain and an identifying User-Agent are non-negotiable (§10.2).

- [ ] **Step 1: Write the failing test**

`tests/test_fetch.py`:
```python
import httpx
import pytest
from bce.fetch import Fetcher, USER_AGENT


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_user_agent_identifies_and_carries_contact_url():
    assert "SunreefPartnerContentBot" in USER_AGENT
    assert "http" in USER_AGENT


def test_robots_allows_when_permitted():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nAllow: /")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/blog") is True


def test_robots_blocks_disallowed_path():
    def handler(request):
        return httpx.Response(200, text="User-agent: *\nDisallow: /private")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/private/x") is False


def test_missing_robots_is_treated_as_allowed():
    def handler(request):
        return httpx.Response(404)
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.robots_allows("https://acme.com/") is True


def test_get_returns_none_when_disallowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        return httpx.Response(200, text="body")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") is None


def test_get_returns_body_when_allowed():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, text="hello")
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") == "hello"


def test_get_returns_none_on_error_status():
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(500)
    f = Fetcher(min_delay=0, client=_client(handler))
    assert f.get("https://acme.com/page") is None


def test_rate_limit_sleeps_between_same_host_requests(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("bce.fetch.time.sleep", lambda s: slept.append(s))
    monkeypatch.setattr("bce.fetch.time.monotonic", lambda: 0.0)

    def handler(request):
        return httpx.Response(200, text="ok")

    f = Fetcher(min_delay=2.0, client=_client(handler))
    f.get("https://acme.com/a")
    f.get("https://acme.com/b")
    assert any(s > 0 for s in slept)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce.fetch'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/fetch.py`:
```python
"""Polite fetcher: robots.txt honoured, per-host rate limit (spec §10.2)."""
import os
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import httpx

CONTACT_URL = os.environ.get("BCE_CONTACT_URL", "https://www.sunreef-yachts.com/")
USER_AGENT = f"SunreefPartnerContentBot/0.1 (+{CONTACT_URL})"


class Fetcher:
    def __init__(self, min_delay: float = 2.0, client: httpx.Client | None = None):
        self.min_delay = min_delay
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True
        )
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._last_hit: dict[str, float] = {}

    def robots_allows(self, url: str) -> bool:
        host = urlparse(url).netloc
        if host not in self._robots:
            self._robots[host] = self._load_robots(url)
        parser = self._robots[host]
        if parser is None:
            return True
        return parser.can_fetch(USER_AGENT, url)

    def _load_robots(self, url: str):
        robots_url = urljoin(url, "/robots.txt")
        try:
            response = self._client.get(robots_url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(response.text.splitlines())
        return parser

    def _throttle(self, host: str) -> None:
        last = self._last_hit.get(host)
        now = time.monotonic()
        if last is not None:
            elapsed = now - last
            if elapsed < self.min_delay:
                time.sleep(self.min_delay - elapsed)
        self._last_hit[host] = time.monotonic()

    def get(self, url: str) -> str | None:
        if not self.robots_allows(url):
            return None
        self._throttle(urlparse(url).netloc)
        try:
            response = self._client.get(url)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        return response.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_fetch.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/fetch.py tests/test_fetch.py
git commit -m "feat: robots-aware rate-limited fetcher"
```

---

### Task 7: Manual broker import

**Files:**
- Create: `broker-content-engine/src/bce/discover.py`
- Test: `broker-content-engine/tests/test_discover.py`

**Interfaces:**
- Consumes: `bce.db` from Task 2
- Produces:
  - `import_csv(conn, csv_text: str) -> int` — inserts brokers with `source='manual'`, returns count inserted. Required columns `name,domain`; optional `region`. Duplicate domains are skipped, not errors.
  - `list_brokers(conn, *, qualified: bool | None = None) -> list[sqlite3.Row]` — ordered by affinity rank (`lists_inventory`, `mentions`, `unknown`, `none`) then name. Ordering only, per spec §4.

- [ ] **Step 1: Write the failing test**

`tests/test_discover.py`:
```python
from bce import db, discover


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def test_import_csv_inserts_rows():
    conn = _conn()
    n = discover.import_csv(conn, "name,domain,region\nAcme,acme.com,Med\n")
    assert n == 1
    row = conn.execute("SELECT * FROM broker").fetchone()
    assert row["name"] == "Acme"
    assert row["domain"] == "acme.com"
    assert row["region"] == "Med"
    assert row["source"] == "manual"


def test_import_csv_skips_duplicate_domains():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\n")
    n = discover.import_csv(conn, "name,domain\nAcme Again,acme.com\n")
    assert n == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_import_csv_tolerates_missing_optional_region():
    conn = _conn()
    assert discover.import_csv(conn, "name,domain\nAcme,acme.com\n") == 1


def test_list_brokers_orders_by_affinity_then_name():
    conn = _conn()
    discover.import_csv(
        conn,
        "name,domain\nZulu,zulu.com\nAlpha,alpha.com\nBravo,bravo.com\n",
    )
    conn.execute("UPDATE broker SET sunreef_affinity='none' WHERE domain='alpha.com'")
    conn.execute(
        "UPDATE broker SET sunreef_affinity='lists_inventory' WHERE domain='zulu.com'"
    )
    conn.execute("UPDATE broker SET sunreef_affinity='mentions' WHERE domain='bravo.com'")
    names = [r["name"] for r in discover.list_brokers(conn)]
    assert names == ["Zulu", "Bravo", "Alpha"]


def test_list_brokers_filters_by_qualified():
    conn = _conn()
    discover.import_csv(conn, "name,domain\nAcme,acme.com\nBeta,beta.com\n")
    conn.execute("UPDATE broker SET qualified=1 WHERE domain='acme.com'")
    conn.execute("UPDATE broker SET qualified=0 WHERE domain='beta.com'")
    assert [r["name"] for r in discover.list_brokers(conn, qualified=True)] == ["Acme"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_discover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce.discover'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/discover.py`:
```python
"""Stage 1 — build the candidate shortlist (spec §5)."""
import csv
import io
import sqlite3

_AFFINITY_RANK = {
    "lists_inventory": 0,
    "mentions": 1,
    "unknown": 2,
    "none": 3,
}


def import_csv(conn: sqlite3.Connection, csv_text: str) -> int:
    reader = csv.DictReader(io.StringIO(csv_text))
    inserted = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        domain = (row.get("domain") or "").strip()
        if not name or not domain:
            continue
        region = (row.get("region") or "").strip() or None
        try:
            conn.execute(
                "INSERT INTO broker (name, domain, region, source) "
                "VALUES (?, ?, ?, 'manual')",
                (name, domain, region),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    return inserted


def list_brokers(
    conn: sqlite3.Connection, *, qualified: bool | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM broker"
    params: tuple = ()
    if qualified is not None:
        sql += " WHERE qualified = ?"
        params = (1 if qualified else 0,)
    rows = conn.execute(sql, params).fetchall()
    return sorted(
        rows,
        key=lambda r: (_AFFINITY_RANK.get(r["sunreef_affinity"], 2), r["name"]),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_discover.py -v`
Expected: PASS, 5 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/discover.py tests/test_discover.py
git commit -m "feat: manual CSV broker import with affinity-ordered listing"
```

---

### Task 8: Qualification orchestrator

**Files:**
- Create: `broker-content-engine/src/bce/qualify.py`
- Test: `broker-content-engine/tests/test_qualify.py`

**Interfaces:**
- Consumes: `bce.db`, `bce.detectors` (`detect_max_length_ft`, `detect_sunreef_affinity`, `find_editorial_urls`, `detect_newsletter`), `bce.fetch.Fetcher`
- Produces:
  - `MIN_LENGTH_FT: int = 60`
  - `qualify_broker(conn, broker_id: int, fetcher) -> dict` — fetches the broker homepage, runs all four detectors, writes `qualified`, `qualified_reason`, `robots_allowed`, `sunreef_affinity`, `affinity_evidence`, `segment_evidence`, `has_editorial`, `has_newsletter`, `newsletter_evidence`; returns the verdict dict with keys `qualified: bool`, `reason: str`.

Verdict rules, in order (amended for spec v0.5 — a newsletter is a qualifying publishing channel):
1. Homepage unreachable or robots-disallowed → `qualified=0`, reason `"unreachable_or_disallowed"`
2. No length ≥ 60ft found → `qualified=0`, reason `"below_length_threshold"`
3. **Neither** an editorial section **nor** a newsletter found → `qualified=0`, reason `"no_publishing_channel"`
4. Otherwise → `qualified=1`, reason `"passed"`

Both channels are detected and recorded independently on every run, whatever the verdict — the UI needs to show which channel a broker offers, and Stage 4 needs it to decide whether the long form, the short form, or both are the deliverable.

Affinity is recorded regardless of verdict and never affects it (spec §4).

**Test amendments for this rule change.** In the test code below, make these three changes and leave everything else exactly as written:
- Rename `test_no_editorial_section_fails` to `test_no_publishing_channel_fails` and change its expected reason from `"no_editorial_section"` to `"no_publishing_channel"`. Its page fixture (`"We sell 80 ft catamarans"`) has neither channel, so it still exercises the right branch.
- Add this test, which is the whole point of the amendment:
```python
def test_newsletter_only_broker_passes():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": "Our 80 ft fleet. Sign up for our newsletter."}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    assert verdict["reason"] == "passed"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_newsletter"] == 1
    assert row["has_editorial"] == 0
```
- Add this test, guarding that an editorial-only broker still passes:
```python
def test_editorial_only_broker_passes():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["has_editorial"] == 1
    assert row["has_newsletter"] == 0
```

- [ ] **Step 1: Write the failing test**

`tests/test_qualify.py`:
```python
from bce import db, discover, qualify


class FakeFetcher:
    def __init__(self, pages: dict[str, str | None]):
        self.pages = pages

    def get(self, url: str) -> str | None:
        return self.pages.get(url)

    def robots_allows(self, url: str) -> bool:
        return self.pages.get(url) is not None


def _conn_with_broker(domain="acme.com"):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nAcme,{domain}\n")
    bid = conn.execute("SELECT id FROM broker").fetchone()["id"]
    return conn, bid


def test_unreachable_homepage_fails_qualification():
    conn, bid = _conn_with_broker()
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher({}))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "unreachable_or_disallowed"


def test_below_threshold_fails():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 40 ft boats'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "below_length_threshold"


def test_no_editorial_section_fails():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": "We sell 80 ft catamarans"}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    assert verdict["reason"] == "no_editorial_section"


def test_passing_broker_is_marked_qualified():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> Our 80 ft fleet'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is True
    assert verdict["reason"] == "passed"
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["qualified"] == 1
    assert row["robots_allowed"] == 1


def test_affinity_recorded_but_does_not_affect_verdict():
    conn, bid = _conn_with_broker()
    # Sunreef mention present, but boat too small -> still fails on length
    pages = {"https://acme.com/": '<a href="/news">News</a> Sunreef for sale, 30 ft'}
    verdict = qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    assert verdict["qualified"] is False
    row = conn.execute("SELECT * FROM broker WHERE id=?", (bid,)).fetchone()
    assert row["sunreef_affinity"] == "lists_inventory"
    assert "Sunreef" in row["affinity_evidence"]


def test_segment_evidence_records_detected_length():
    conn, bid = _conn_with_broker()
    pages = {"https://acme.com/": '<a href="/blog">Blog</a> 90 ft yachts'}
    qualify.qualify_broker(conn, bid, FakeFetcher(pages))
    row = conn.execute("SELECT segment_evidence FROM broker WHERE id=?", (bid,)).fetchone()
    assert "90" in row["segment_evidence"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_qualify.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce.qualify'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/qualify.py`:
```python
"""Stage 2 — qualification (spec §5).

Affinity is recorded here but never influences the verdict (spec §4).
"""
import sqlite3

from bce.detectors import (
    detect_max_length_ft,
    detect_sunreef_affinity,
    find_editorial_urls,
)

MIN_LENGTH_FT = 60


def _save(conn, broker_id, *, qualified, reason, robots_allowed,
          affinity, evidence, segment_evidence):
    conn.execute(
        "UPDATE broker SET qualified=?, qualified_reason=?, robots_allowed=?, "
        "sunreef_affinity=?, affinity_evidence=?, segment_evidence=? WHERE id=?",
        (
            1 if qualified else 0, reason, 1 if robots_allowed else 0,
            affinity, evidence, segment_evidence, broker_id,
        ),
    )
    conn.commit()
    return {"qualified": qualified, "reason": reason}


def qualify_broker(conn: sqlite3.Connection, broker_id: int, fetcher) -> dict:
    row = conn.execute(
        "SELECT domain FROM broker WHERE id=?", (broker_id,)
    ).fetchone()
    url = f"https://{row['domain']}/"

    html = fetcher.get(url)
    if html is None:
        return _save(
            conn, broker_id, qualified=False, reason="unreachable_or_disallowed",
            robots_allowed=False, affinity="unknown", evidence=None,
            segment_evidence=None,
        )

    affinity, evidence = detect_sunreef_affinity(html)
    length_ft = detect_max_length_ft(html)
    segment_evidence = f"max_detected_length_ft={length_ft}" if length_ft else None

    if length_ft is None or length_ft < MIN_LENGTH_FT:
        return _save(
            conn, broker_id, qualified=False, reason="below_length_threshold",
            robots_allowed=True, affinity=affinity, evidence=evidence,
            segment_evidence=segment_evidence,
        )

    if not find_editorial_urls(html, url):
        return _save(
            conn, broker_id, qualified=False, reason="no_editorial_section",
            robots_allowed=True, affinity=affinity, evidence=evidence,
            segment_evidence=segment_evidence,
        )

    return _save(
        conn, broker_id, qualified=True, reason="passed",
        robots_allowed=True, affinity=affinity, evidence=evidence,
        segment_evidence=segment_evidence,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_qualify.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Commit**

```bash
git add src/bce/qualify.py tests/test_qualify.py
git commit -m "feat: qualification orchestrator with affinity isolated from verdict"
```

---

### Task 9: CLI with volume cap enforcement

**Files:**
- Create: `broker-content-engine/src/bce/cli.py`
- Modify: `broker-content-engine/pyproject.toml`
- Test: `broker-content-engine/tests/test_cli.py`

**Interfaces:**
- Consumes: `bce.db`, `bce.discover`, `bce.qualify`, `bce.fetch`
- Produces:
  - `MAX_BROKERS: int = 50`
  - `cmd_init(db_path: str) -> int`
  - `cmd_import(db_path: str, csv_path: str) -> int` — refuses to exceed `MAX_BROKERS` (spec §6)
  - `cmd_qualify(db_path: str, limit: int = 20) -> int`
  - `cmd_list(db_path: str) -> int`
  - `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: Write the failing test**

`tests/test_cli.py`:
```python
from bce import cli, db, discover


def test_init_creates_schema(tmp_path):
    p = tmp_path / "t.db"
    assert cli.cmd_init(str(p)) == 0
    conn = db.connect(str(p))
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "broker" in names


def test_import_respects_volume_cap(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    rows = "name,domain\n" + "".join(
        f"B{i},b{i}.com\n" for i in range(cli.MAX_BROKERS + 5)
    )
    csv_file = tmp_path / "in.csv"
    csv_file.write_text(rows)
    rc = cli.cmd_import(str(p), str(csv_file))
    assert rc == 1
    assert "cap" in capsys.readouterr().out.lower()
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 0


def test_import_under_cap_succeeds(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    csv_file = tmp_path / "in.csv"
    csv_file.write_text("name,domain\nAcme,acme.com\n")
    assert cli.cmd_import(str(p), str(csv_file)) == 0
    conn = db.connect(str(p))
    assert conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"] == 1


def test_list_prints_broker(tmp_path, capsys):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    conn = db.connect(str(p))
    discover.import_csv(conn, "name,domain\nAcme,acme.com\n")
    assert cli.cmd_list(str(p)) == 0
    assert "Acme" in capsys.readouterr().out


def test_main_dispatches_unknown_command():
    assert cli.main(["nonsense"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bce.cli'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/cli.py`:
```python
"""CLI entry point. Enforces the spec §6 volume cap."""
import argparse
import sys
from pathlib import Path

from bce import db, discover, qualify
from bce.fetch import Fetcher

MAX_BROKERS = 50
DEFAULT_QUALIFY_LIMIT = 20


def cmd_init(db_path: str) -> int:
    conn = db.connect(db_path)
    db.init_schema(conn)
    print(f"initialized {db_path}")
    return 0


def cmd_import(db_path: str, csv_path: str) -> int:
    conn = db.connect(db_path)
    db.init_schema(conn)
    existing = conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"]
    text = Path(csv_path).read_text()
    incoming = max(0, len(text.strip().splitlines()) - 1)
    if existing + incoming > MAX_BROKERS:
        print(
            f"refused: {existing}+{incoming} exceeds the {MAX_BROKERS}-broker cap "
            f"(spec section 6). Trim the CSV or raise the cap deliberately."
        )
        return 1
    print(f"imported {discover.import_csv(conn, text)} brokers")
    return 0


def cmd_qualify(db_path: str, limit: int = DEFAULT_QUALIFY_LIMIT) -> int:
    conn = db.connect(db_path)
    fetcher = Fetcher()
    rows = conn.execute(
        "SELECT id, domain FROM broker WHERE qualified IS NULL LIMIT ?", (limit,)
    ).fetchall()
    for row in rows:
        verdict = qualify.qualify_broker(conn, row["id"], fetcher)
        print(f"{row['domain']}: {verdict['reason']}")
    return 0


def cmd_list(db_path: str) -> int:
    conn = db.connect(db_path)
    for row in discover.list_brokers(conn):
        state = {1: "qualified", 0: "rejected"}.get(row["qualified"], "pending")
        print(f"{row['name']:<30} {row['domain']:<28} {row['sunreef_affinity']:<16} {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bce")
    parser.add_argument("--db", default="bce.db")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    p_import = sub.add_parser("import")
    p_import.add_argument("csv")
    p_qualify = sub.add_parser("qualify")
    p_qualify.add_argument("--limit", type=int, default=DEFAULT_QUALIFY_LIMIT)
    sub.add_parser("list")

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args.db)
    if args.command == "import":
        return cmd_import(args.db, args.csv)
    if args.command == "qualify":
        return cmd_qualify(args.db, args.limit)
    if args.command == "list":
        return cmd_list(args.db)
    print("unknown command", file=sys.stderr)
    return 2
```

Add to `pyproject.toml`:
```toml
[project.scripts]
bce = "bce.cli:main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS, all tests (5 new in test_cli.py)

- [ ] **Step 5: Commit**

```bash
git add src/bce/cli.py tests/test_cli.py pyproject.toml
git commit -m "feat: CLI with volume cap enforcement"
```

---

## Self-Review

**1. Spec coverage.** Stage 1 (§5) → Tasks 7, 9. Stage 2 (§5) → Tasks 3–6, 8. Data model (§8) → Task 2. Volume cap (§6) → Task 9. Crawling constraints (§10.2) → Task 6. Affinity ordering-only (§4) → Tasks 4, 7, 8 (`test_affinity_recorded_but_does_not_affect_verdict` is the guard).

**Deliberate gaps, deferred to later plans, not omissions:**
- Stage 2's "editorial updated within 12 months" recency check. Task 5 finds editorial URLs; recency needs `htmldate` against fetched articles, which belongs with Stage 3's article extraction. Qualification is therefore slightly permissive in this plan — a stale blog passes. Flagged so the next plan closes it.
- Stages 3–4 (voice profile, drafting) — next plan.
- Stages 5–7 and the UI (§9) — third plan.
- Near-duplication check (§10.3) and Sunreef fact verification (§10.4) — belong with drafting.

**2. Placeholder scan.** No TBDs. Every code step contains runnable code. The one unresolved value — the contact URL in the User-Agent — has a working default, an env override, and an explicit confirm-with-Luis note in Global Constraints.

**3. Type consistency.** `detect_max_length_ft`, `detect_sunreef_affinity`, `find_editorial_urls` are defined in Tasks 3–5 and consumed in Task 8 under those exact names. `Fetcher.get`/`robots_allows` defined in Task 6, and Task 8's `FakeFetcher` implements exactly that two-method surface. `db.connect`/`init_schema`/`SCHEMA_TABLES` defined in Task 2 and used in Tasks 7–9. Affinity enum values match the `CHECK` constraint in Task 2 and `_AFFINITY_RANK` in Task 7.
