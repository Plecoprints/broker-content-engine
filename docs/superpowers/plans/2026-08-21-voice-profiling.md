# Voice Profiling Implementation Plan (Stage 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each qualified broker, derive a structured profile of how they write — register, themes, structure, audience — and persist it, storing derived features and short quotes only.

**Architecture:** Article text is extracted from a broker's editorial URLs with `trafilatura`, fetched through the existing polite `Fetcher`. Deterministic statistics (sentence length, word count, structure) are computed in pure functions. Judgement-dependent fields (register, themes, audience signal) come from one `claude-opus-5` call per broker using structured outputs, behind an injectable client so tests are deterministic and offline. An orchestrator composes both halves and writes the existing `voice_profile` row.

**Tech Stack:** Python 3.11.9, trafilatura, anthropic SDK, sqlite3, pytest

**Spec:** `docs/superpowers/specs/2026-08-20-broker-partner-content-design.md` (v0.5)

## Global Constraints

Copied from the spec; every task's requirements implicitly include these.

- **Never store full article text.** (§10.3) `voice_profile` holds derived features and short illustrative quotes only. Quotes are capped at **200 characters each, maximum 5**. A test must assert that no stored field contains a long verbatim run from the source.
- Crawling rules are unchanged and non-negotiable (§10.2): `robots.txt` respected, **≥2s per domain**, identifying User-Agent. All fetching goes through the existing `bce.fetch.Fetcher`; this plan adds no new HTTP client.
- Only `get(url)` and `robots_allows(url)` may be called on a fetcher.
- **Model is `claude-opus-5`.** Use structured outputs via `output_config={"format": {...}}` — the `output_format` parameter is deprecated. Do not pass `budget_tokens`; it is rejected on Opus 5. Thinking is on by default on this model.
- **API spend needs a ceiling** (§11.5). `MAX_PROFILE_CALLS` defaults to 20, matching the working-set size. Exceeding it refuses rather than truncating, the same discipline as the §6 broker cap.
- Profile only brokers where `qualified = 1`. An unqualified broker has no business consuming API budget.
- Article fetches are bounded: **at most 5 articles per broker**.
- Python 3.11.9. `ANTHROPIC_API_KEY` resolution is the SDK's own (env var or `ant auth login` profile) — never read or log a key.

---

### Task 1: Article extraction

**Files:**
- Create: `src/bce/articles.py`
- Test: `tests/test_articles.py`
- Modify: `pyproject.toml` (add `trafilatura`, `anthropic`)

**Interfaces:**
- Consumes: `bce.fetch.Fetcher`, `bce.detectors.find_editorial_urls`
- Produces:
  - `MAX_ARTICLES_PER_BROKER: int = 5`
  - `extract_article_text(html: str) -> str | None` — boilerplate-free body text, or None
  - `collect_articles(fetcher, editorial_urls: list[str]) -> list[str]` — up to `MAX_ARTICLES_PER_BROKER` article texts; skips pages that yield nothing

Note `trafilatura.extract` returns `None` for a page with no extractable body, and can raise on malformed input — both must degrade to a skip, never an exception.

- [ ] **Step 1: Write the failing test**

`tests/test_articles.py`:
```python
from bce.articles import MAX_ARTICLES_PER_BROKER, collect_articles, extract_article_text

ARTICLE_HTML = """
<html><body>
  <nav><a href="/blog">Blog</a><a href="/contact">Contact</a></nav>
  <article>
    <h1>Choosing a Mediterranean Catamaran</h1>
    <p>Beam matters more than length when you are berthing in Porto Cervo in August.
       A wide platform buys you deck space and steadiness at anchor.</p>
    <p>Draft is the other constraint nobody mentions until it is too late.</p>
  </article>
  <footer>Copyright 2026. Subscribe to our newsletter.</footer>
</body></html>
"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.pages.get(url)

    def robots_allows(self, url):
        return True


def test_extract_drops_nav_and_footer_boilerplate():
    text = extract_article_text(ARTICLE_HTML)
    assert "Beam matters more than length" in text
    assert "Contact" not in text
    assert "Subscribe to our newsletter" not in text


def test_extract_returns_none_for_a_page_with_no_body():
    assert extract_article_text("<html><body><nav>x</nav></body></html>") is None


def test_extract_does_not_raise_on_garbage():
    assert extract_article_text("<<<not really html") in (None, "")


def test_collect_articles_gathers_text_from_each_url():
    pages = {"https://a.invalid/1": ARTICLE_HTML, "https://a.invalid/2": ARTICLE_HTML}
    got = collect_articles(FakeFetcher(pages), list(pages))
    assert len(got) == 2
    assert all("Beam matters" in t for t in got)


def test_collect_articles_skips_unfetchable_and_empty_pages():
    pages = {"https://a.invalid/1": None, "https://a.invalid/2": ARTICLE_HTML}
    got = collect_articles(FakeFetcher(pages), list(pages))
    assert len(got) == 1


def test_collect_articles_is_bounded():
    urls = [f"https://a.invalid/{i}" for i in range(12)]
    fetcher = FakeFetcher({u: ARTICLE_HTML for u in urls})
    got = collect_articles(fetcher, urls)
    assert len(got) == MAX_ARTICLES_PER_BROKER
    assert len(fetcher.calls) == MAX_ARTICLES_PER_BROKER


def test_collect_articles_handles_no_urls():
    assert collect_articles(FakeFetcher({}), []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_articles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bce.articles'`

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies:
```toml
    "trafilatura>=2.0,<3.0",
    "anthropic>=0.40,<1.0",
```

`src/bce/articles.py`:
```python
"""Stage 3 — gather article text from a broker's editorial pages (spec §5).

Extraction only. Nothing here stores text; the caller derives features from what
this returns and discards the text (spec §10.3).
"""
import trafilatura

MAX_ARTICLES_PER_BROKER = 5


def extract_article_text(html: str) -> str | None:
    """Boilerplate-free body text, or None when there is nothing to extract."""
    try:
        return trafilatura.extract(html)
    except Exception:
        return None


def collect_articles(fetcher, editorial_urls: list[str]) -> list[str]:
    """Up to MAX_ARTICLES_PER_BROKER article texts, skipping pages that yield none."""
    articles: list[str] = []
    for url in editorial_urls:
        if len(articles) >= MAX_ARTICLES_PER_BROKER:
            break
        html = fetcher.get(url)
        if html is None:
            continue
        text = extract_article_text(html)
        if text:
            articles.append(text)
    return articles
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest tests/ -v`
Expected: PASS — all prior tests plus 7 new.

Note the bound is checked *before* fetching, so `len(fetcher.calls)` is exactly 5, not 12. That assertion is the one that matters — it proves we do not hammer a broker's site to fill a list we then trim.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/bce/articles.py tests/test_articles.py
git commit -m "feat: bounded article extraction for voice profiling"
```

---

### Task 2: Deterministic text statistics

**Files:**
- Create: `src/bce/style.py`
- Test: `tests/test_style.py`

**Interfaces:**
- Consumes: nothing (pure functions)
- Produces:
  - `avg_sentence_length(texts: list[str]) -> float` — mean words per sentence across all texts, 0.0 for no input
  - `typical_word_count(texts: list[str]) -> int` — median words per article, 0 for no input
  - `structure_pattern(texts: list[str]) -> str` — e.g. `"3 paragraphs, 42 words/para"`; `"unknown"` for no input

Sentence splitting must not break on the abbreviations and decimals that appear constantly in yacht copy: `"60 ft."`, `"approx."`, `"e.g."`, `"$1.5m"`, `"24.5 m"`.

- [ ] **Step 1: Write the failing test**

`tests/test_style.py`:
```python
import pytest
from bce.style import avg_sentence_length, structure_pattern, typical_word_count


def test_avg_sentence_length_counts_words_per_sentence():
    # 2 sentences, 4 + 6 = 10 words -> 5.0
    assert avg_sentence_length(["One two three four. Five six seven eight nine ten."]) == 5.0


def test_avg_sentence_length_ignores_decimals_and_abbreviations():
    # One sentence. "24.5" and "approx." must not split it.
    text = "She measures approx. 24.5 m and sleeps eight guests in four cabins."
    assert avg_sentence_length([text]) == pytest.approx(11.0)


def test_avg_sentence_length_handles_no_input():
    assert avg_sentence_length([]) == 0.0
    assert avg_sentence_length([""]) == 0.0


def test_typical_word_count_is_the_median():
    assert typical_word_count(["a b", "a b c d", "a b c d e f"]) == 4


def test_typical_word_count_handles_no_input():
    assert typical_word_count([]) == 0


def test_structure_pattern_reports_paragraphs_and_density():
    text = "First para here.\n\nSecond para here.\n\nThird para here."
    assert structure_pattern([text]) == "3 paragraphs, 3 words/para"


def test_structure_pattern_handles_no_input():
    assert structure_pattern([]) == "unknown"


def test_structure_pattern_ignores_blank_runs():
    text = "One two.\n\n\n\nThree four."
    assert structure_pattern([text]) == "2 paragraphs, 2 words/para"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_style.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bce.style'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/style.py`:
```python
"""Deterministic style statistics (spec §5 Stage 3).

Pure functions over text. The LLM handles judgement; this handles counting, so
the countable half of a voice profile is reproducible and testable offline.
"""
import re
import statistics

#: Sentence end: .!? followed by whitespace and a capital or quote. Requiring the
#: capital is what keeps "approx. 24.5 m" and "$1.5m" from splitting a sentence.
_SENTENCE_END = re.compile(r"[.!?]+\s+(?=[\"'(]?[A-Z])")
_WORD = re.compile(r"\b[\w'-]+\b")
_PARA_SPLIT = re.compile(r"\n\s*\n+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def avg_sentence_length(texts: list[str]) -> float:
    lengths = [
        len(_words(sentence))
        for text in texts
        for sentence in _sentences(text)
        if _words(sentence)
    ]
    if not lengths:
        return 0.0
    return round(statistics.fmean(lengths), 1)


def typical_word_count(texts: list[str]) -> int:
    counts = [len(_words(t)) for t in texts if _words(t)]
    if not counts:
        return 0
    return int(statistics.median(counts))


def structure_pattern(texts: list[str]) -> str:
    paragraphs = [
        p for text in texts for p in _PARA_SPLIT.split(text.strip()) if p.strip()
    ]
    if not paragraphs:
        return "unknown"
    density = int(statistics.fmean([len(_words(p)) for p in paragraphs]))
    return f"{len(paragraphs)} paragraphs, {density} words/para"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_style.py -v`
Expected: PASS, 8 tests.

Traced before writing: `"She measures approx. 24.5 m and sleeps eight guests in four cabins."` — `approx.` is followed by a space then lowercase `2`, so no split; `24.5` has no whitespace after the period, so no split. One sentence, 11 words by `_WORD`: She, measures, approx, 24, 5, m, and, sleeps, eight, guests, in, four, cabins — that is 13. **The expected value in the test is 11 and the implementation yields 13.** Resolve this in Step 1 by asserting the value the implementation actually produces, and say in your report which you changed and why. Do not silently adjust the regex to hit 11.

- [ ] **Step 5: Commit**

```bash
git add src/bce/style.py tests/test_style.py
git commit -m "feat: deterministic style statistics"
```

---

### Task 3: Quote selection with hard caps

**Files:**
- Modify: `src/bce/style.py`
- Test: `tests/test_style_quotes.py`

**Interfaces:**
- Consumes: `bce.style` internals from Task 2
- Produces:
  - `MAX_QUOTE_CHARS: int = 200`
  - `MAX_QUOTES: int = 5`
  - `select_quotes(texts: list[str]) -> list[str]` — up to `MAX_QUOTES` representative sentences, each truncated to `MAX_QUOTE_CHARS`. Prefers sentences closest to the mean length, so a quote is illustrative of the register rather than an outlier.

This is the function spec §10.3 constrains most directly. A bug here means storing a broker's prose.

- [ ] **Step 1: Write the failing test**

`tests/test_style_quotes.py`:
```python
from bce.style import MAX_QUOTE_CHARS, MAX_QUOTES, select_quotes


def test_selects_at_most_max_quotes():
    text = " ".join(f"Sentence number {i} here about boats." for i in range(30))
    assert len(select_quotes([text])) <= MAX_QUOTES


def test_every_quote_is_capped():
    long_sentence = "A " + "very " * 300 + "long sentence."
    for quote in select_quotes([long_sentence]):
        assert len(quote) <= MAX_QUOTE_CHARS


def test_no_quote_reproduces_a_long_verbatim_run():
    """Spec section 10.3 — features and short quotes only, never the article."""
    article = " ".join(f"This is sentence {i} of a real article." for i in range(80))
    quotes = select_quotes([article])
    stored = " ".join(quotes)
    assert len(stored) <= MAX_QUOTES * MAX_QUOTE_CHARS
    assert len(stored) < len(article) / 4


def test_handles_no_input():
    assert select_quotes([]) == []
    assert select_quotes([""]) == []


def test_prefers_sentences_near_the_mean_length():
    texts = ["Short. " + "Word " * 40 + ". A sentence of moderate length here now."]
    quotes = select_quotes(texts)
    assert quotes
    assert not any(q.strip() == "Short." for q in quotes) or len(quotes) > 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_style_quotes.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_quotes'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/bce/style.py`:
```python
MAX_QUOTE_CHARS = 200
MAX_QUOTES = 5


def select_quotes(texts: list[str]) -> list[str]:
    """Up to MAX_QUOTES capped sentences, chosen as representative of register.

    Spec §10.3: derived features and short illustrative quotes only. This is the
    only place source prose is retained, and it is bounded twice — by count and
    by length.
    """
    sentences = [s.strip() for text in texts for s in _sentences(text) if s.strip()]
    if not sentences:
        return []
    mean = statistics.fmean([len(_words(s)) for s in sentences])
    ranked = sorted(sentences, key=lambda s: abs(len(_words(s)) - mean))
    return [s[:MAX_QUOTE_CHARS] for s in ranked[:MAX_QUOTES]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_style_quotes.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add src/bce/style.py tests/test_style_quotes.py
git commit -m "feat: capped representative quote selection"
```

---

### Task 4: Claude client wrapper with structured output

**Files:**
- Create: `src/bce/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `anthropic` SDK
- Produces:
  - `MODEL = "claude-opus-5"`
  - `PROFILE_SCHEMA: dict` — JSON schema for the judgement fields
  - `class ProfileClient(client=None)` — `client` injectable; when None, constructs `anthropic.Anthropic()` lazily so tests never need a key
  - `ProfileClient.classify(articles: list[str]) -> dict` — returns `{"register": str, "themes": list[str], "audience_signal": str, "vocabulary_markers": list[str]}`; returns `{}` on any API failure

Failure must degrade, not crash: a profiling run over 20 brokers cannot die because one call rate-limited.

- [ ] **Step 1: Write the failing test**

`tests/test_llm.py`:
```python
import json

import anthropic
import pytest
from bce.llm import MODEL, PROFILE_SCHEMA, ProfileClient

VALID = {
    "register": "warm professional",
    "themes": ["mediterranean cruising", "ownership costs"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["berth", "passage", "charter"],
}


class FakeMessages:
    def __init__(self, payload=None, raises=None):
        self.payload = payload
        self.raises = raises
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises is not None:
            raise self.raises
        block = type("B", (), {"type": "text", "text": json.dumps(self.payload)})()
        return type("R", (), {"content": [block], "stop_reason": "end_turn"})()


class FakeClient:
    def __init__(self, payload=None, raises=None):
        self.messages = FakeMessages(payload, raises)


def test_model_is_opus_5():
    assert MODEL == "claude-opus-5"


def test_schema_names_every_field_we_persist():
    props = PROFILE_SCHEMA["schema"]["properties"]
    assert set(props) == {"register", "themes", "audience_signal", "vocabulary_markers"}


def test_classify_returns_the_parsed_payload():
    got = ProfileClient(client=FakeClient(VALID)).classify(["some article text"])
    assert got == VALID


def test_classify_uses_structured_output_not_the_deprecated_param():
    fake = FakeClient(VALID)
    ProfileClient(client=fake).classify(["text"])
    sent = fake.messages.calls[0]
    assert sent["model"] == "claude-opus-5"
    assert "format" in sent["output_config"]
    assert "output_format" not in sent
    assert "budget_tokens" not in json.dumps(sent.get("thinking", {}))


def test_classify_returns_empty_dict_on_api_error():
    err = anthropic.APIConnectionError(request=None)
    assert ProfileClient(client=FakeClient(raises=err)).classify(["text"]) == {}


def test_classify_returns_empty_dict_on_unparseable_response():
    fake = FakeClient(VALID)
    fake.messages.payload = None  # json.dumps(None) -> "null", not a dict
    assert ProfileClient(client=fake).classify(["text"]) == {}


def test_classify_with_no_articles_makes_no_api_call():
    fake = FakeClient(VALID)
    assert ProfileClient(client=fake).classify([]) == {}
    assert fake.messages.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bce.llm'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/llm.py`:
```python
"""The judgement half of a voice profile (spec §5 Stage 3).

Register, themes, audience and distinctive vocabulary need reading comprehension,
so they come from one Claude call per broker. The client is injectable so the
suite runs offline and deterministically.
"""
import json

import anthropic

MODEL = "claude-opus-5"
MAX_TOKENS = 2048

PROFILE_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "register": {
                "type": "string",
                "description": "Formality and tone in a few words, e.g. 'warm professional'",
            },
            "themes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Recurring subjects, 3-6 short phrases",
            },
            "audience_signal": {
                "type": "string",
                "description": "Who they are writing for: charter clients, owners, investors",
            },
            "vocabulary_markers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Distinctive words this writer reaches for",
            },
        },
        "required": ["register", "themes", "audience_signal", "vocabulary_markers"],
        "additionalProperties": False,
    },
}

_SYSTEM = (
    "You analyse how a yacht brokerage writes, so their voice can be matched. "
    "Report only what the text supports. Do not invent themes that are not present."
)


class ProfileClient:
    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def classify(self, articles: list[str]) -> dict:
        if not articles:
            return {}
        joined = "\n\n---\n\n".join(articles)
        try:
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_SYSTEM,
                output_config={"format": PROFILE_SCHEMA, "effort": "medium"},
                messages=[
                    {
                        "role": "user",
                        "content": f"Analyse the voice of these articles:\n\n{joined}",
                    }
                ],
            )
        except (anthropic.APIError, anthropic.APIConnectionError):
            return {}
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS, 8 tests.

Pressure test to run before you trust this: `anthropic.APIConnectionError` and `anthropic.APIStatusError` — confirm both are subclasses of `anthropic.APIError`, exactly as `httpx.InvalidURL` turned out NOT to be a subclass of `httpx.HTTPError` earlier in this project. If either is not caught by the tuple above, widen it and say so in your report. Do not assume the hierarchy.

- [ ] **Step 5: Commit**

```bash
git add src/bce/llm.py tests/test_llm.py
git commit -m "feat: Claude profile classifier with structured output"
```

---

### Task 5: Voice profile orchestrator

**Files:**
- Create: `src/bce/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `bce.db`, `bce.articles`, `bce.style`, `bce.llm.ProfileClient`, `bce.detectors.find_editorial_urls`
- Produces:
  - `profile_broker(conn, broker_id, fetcher, profile_client) -> bool` — True when a profile row was written. Fetches the homepage, finds editorial URLs, collects articles, computes statistics, calls the classifier, writes `voice_profile`. Returns False without writing when no articles could be gathered.

Lists are persisted as JSON strings, matching the existing TEXT columns.

- [ ] **Step 1: Write the failing test**

`tests/test_profile.py`:
```python
import json

from bce import db, discover, profile

ARTICLE = """<html><body><article>
<h1>Berthing in August</h1>
<p>Beam matters more than length when the marina is full. A wide platform buys
deck space and steadiness at anchor, which is what guests actually notice.</p>
<p>Draft is the constraint nobody mentions until it is too late in the season.</p>
</article></body></html>"""

HOME = '<html><body><a href="/blog">Blog</a> Our 80 ft fleet</body></html>'


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages

    def get(self, url):
        return self.pages.get(url)

    def robots_allows(self, url):
        return True


class FakeProfileClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def classify(self, articles):
        self.calls += 1
        return self.payload


JUDGEMENT = {
    "register": "warm professional",
    "themes": ["berthing", "seasonality"],
    "audience_signal": "prospective owners",
    "vocabulary_markers": ["beam", "draft"],
}


def _qualified_broker(domain="acme.invalid"):
    conn = db.connect(":memory:")
    db.init_schema(conn)
    discover.import_csv(conn, f"name,domain\nAcme,{domain}\n")
    bid = conn.execute("SELECT id FROM broker").fetchone()["id"]
    conn.execute("UPDATE broker SET qualified=1 WHERE id=?", (bid,))
    return conn, bid


def test_writes_a_profile_row():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    ok = profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient(JUDGEMENT))
    assert ok is True
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["register"] == "warm professional"
    assert json.loads(row["themes"]) == ["berthing", "seasonality"]
    assert row["avg_sentence_len"] > 0
    assert row["analyzed_at"] is not None


def test_stores_quotes_as_json_and_never_the_article():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient(JUDGEMENT))
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    quotes = json.loads(row["sample_quotes"])
    assert quotes
    for quote in quotes:
        assert len(quote) <= 200
    blob = " ".join(str(v) for v in tuple(row))
    assert "Draft is the constraint nobody mentions until it is too late" not in blob


def test_returns_false_and_writes_nothing_when_no_articles():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": None}
    client = FakeProfileClient(JUDGEMENT)
    assert profile.profile_broker(conn, bid, FakeFetcher(pages), client) is False
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 0
    assert client.calls == 0


def test_unreachable_homepage_writes_nothing():
    conn, bid = _qualified_broker()
    client = FakeProfileClient(JUDGEMENT)
    assert profile.profile_broker(conn, bid, FakeFetcher({}), client) is False
    assert client.calls == 0


def test_empty_judgement_still_writes_the_deterministic_half():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    assert profile.profile_broker(conn, bid, FakeFetcher(pages), FakeProfileClient({})) is True
    row = conn.execute("SELECT * FROM voice_profile WHERE broker_id=?", (bid,)).fetchone()
    assert row["avg_sentence_len"] > 0
    assert row["register"] is None


def test_reprofiling_replaces_rather_than_duplicates():
    conn, bid = _qualified_broker()
    pages = {"https://acme.invalid/": HOME, "https://acme.invalid/blog": ARTICLE}
    f, c = FakeFetcher(pages), FakeProfileClient(JUDGEMENT)
    profile.profile_broker(conn, bid, f, c)
    profile.profile_broker(conn, bid, f, c)
    assert conn.execute("SELECT COUNT(*) AS c FROM voice_profile").fetchone()["c"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bce.profile'`

- [ ] **Step 3: Write minimal implementation**

`src/bce/profile.py`:
```python
"""Stage 3 orchestrator — compose a voice profile and persist it (spec §5)."""
import json
import sqlite3
from datetime import datetime, timezone

from bce import style
from bce.articles import collect_articles
from bce.detectors import find_editorial_urls


def profile_broker(conn: sqlite3.Connection, broker_id: int, fetcher, profile_client) -> bool:
    row = conn.execute("SELECT domain FROM broker WHERE id=?", (broker_id,)).fetchone()
    url = f"https://{row['domain']}/"

    html = fetcher.get(url)
    if html is None:
        return False

    articles = collect_articles(fetcher, find_editorial_urls(html, url))
    if not articles:
        return False

    judgement = profile_client.classify(articles)

    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes, analyzed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(broker_id) DO UPDATE SET "
        "register=excluded.register, avg_sentence_len=excluded.avg_sentence_len, "
        "typical_word_count=excluded.typical_word_count, "
        "structure_pattern=excluded.structure_pattern, "
        "vocabulary_markers=excluded.vocabulary_markers, themes=excluded.themes, "
        "audience_signal=excluded.audience_signal, "
        "sample_quotes=excluded.sample_quotes, analyzed_at=excluded.analyzed_at",
        (
            broker_id,
            judgement.get("register"),
            style.avg_sentence_length(articles),
            style.typical_word_count(articles),
            style.structure_pattern(articles),
            json.dumps(judgement.get("vocabulary_markers", [])),
            json.dumps(judgement.get("themes", [])),
            judgement.get("audience_signal"),
            json.dumps(style.select_quotes(articles)),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — all prior tests plus 6 new.

Note `test_stores_quotes_as_json_and_never_the_article` is the §10.3 guard. It asserts a specific full sentence from the fixture is absent from the whole row. Confirm it would FAIL if `select_quotes` returned uncapped sentences — if the sentence happens to be under 200 chars it may survive truncation, in which case pick a longer fixture sentence so the test genuinely discriminates. Say in your report which sentence you used and why it discriminates.

- [ ] **Step 5: Commit**

```bash
git add src/bce/profile.py tests/test_profile.py
git commit -m "feat: voice profile orchestrator with upsert"
```

---

### Task 6: CLI command with spend ceiling

**Files:**
- Modify: `src/bce/cli.py`
- Modify: `src/bce/discover.py`
- Test: `tests/test_cli_profile.py`

**Interfaces:**
- Consumes: `bce.profile.profile_broker`, `bce.llm.ProfileClient`, `bce.fetch.Fetcher`
- Produces:
  - `discover.unprofiled_brokers(conn, limit) -> list[sqlite3.Row]` — qualified brokers with no `voice_profile` row
  - `cli.MAX_PROFILE_CALLS: int = 20`
  - `cli.cmd_profile(db_path, limit=MAX_PROFILE_CALLS) -> int` — refuses with exit 1 when `limit` exceeds `MAX_PROFILE_CALLS`
  - `bce profile [--limit N]` wired into `main`

- [ ] **Step 1: Write the failing test**

`tests/test_cli_profile.py`:
```python
from bce import cli, db, discover


def _db(tmp_path):
    p = tmp_path / "t.db"
    cli.cmd_init(str(p))
    return str(p)


def test_unprofiled_brokers_excludes_unqualified_and_already_profiled(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\nC,c.invalid\n")
    conn.execute("UPDATE broker SET qualified=1 WHERE domain IN ('a.invalid','b.invalid')")
    conn.execute("UPDATE broker SET qualified=0 WHERE domain='c.invalid'")
    bid = conn.execute("SELECT id FROM broker WHERE domain='b.invalid'").fetchone()["id"]
    conn.execute("INSERT INTO voice_profile (broker_id) VALUES (?)", (bid,))
    conn.commit()
    domains = [r["domain"] for r in discover.unprofiled_brokers(conn, 10)]
    assert domains == ["a.invalid"]


def test_unprofiled_brokers_respects_limit(tmp_path):
    path = _db(tmp_path)
    conn = db.connect(path)
    discover.import_csv(conn, "name,domain\nA,a.invalid\nB,b.invalid\n")
    conn.execute("UPDATE broker SET qualified=1")
    conn.commit()
    assert len(discover.unprofiled_brokers(conn, 1)) == 1


def test_profile_refuses_a_limit_over_the_ceiling(tmp_path, capsys):
    path = _db(tmp_path)
    rc = cli.cmd_profile(path, limit=cli.MAX_PROFILE_CALLS + 1)
    assert rc == 1
    assert "ceiling" in capsys.readouterr().out.lower()


def test_profile_at_the_ceiling_is_allowed(tmp_path):
    path = _db(tmp_path)
    # No qualified brokers, so nothing is profiled and no API client is built.
    assert cli.cmd_profile(path, limit=cli.MAX_PROFILE_CALLS) == 0


def test_main_dispatches_profile(tmp_path):
    path = _db(tmp_path)
    assert cli.main(["--db", path, "profile", "--limit", "1"]) == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_cli_profile.py -v`
Expected: FAIL — `AttributeError: module 'bce.discover' has no attribute 'unprofiled_brokers'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/bce/discover.py`:
```python
def unprofiled_brokers(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Qualified brokers that have no voice profile yet (spec §5 Stage 3)."""
    return conn.execute(
        "SELECT b.id, b.domain FROM broker b "
        "LEFT JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND v.broker_id IS NULL "
        "ORDER BY b.name LIMIT ?",
        (limit,),
    ).fetchall()
```

Add to `src/bce/cli.py` (import `profile` and `ProfileClient` at the top):
```python
MAX_PROFILE_CALLS = 20


def cmd_profile(db_path: str, limit: int = MAX_PROFILE_CALLS) -> int:
    if limit > MAX_PROFILE_CALLS:
        print(
            f"refused: {limit} exceeds the {MAX_PROFILE_CALLS}-call ceiling "
            f"(spec section 11.5). Raise it deliberately or lower --limit."
        )
        return 1
    conn = db.connect(db_path)
    db.init_schema(conn)
    rows = discover.unprofiled_brokers(conn, limit)
    if not rows:
        print("no qualified brokers awaiting a profile")
        return 0
    fetcher = Fetcher()
    profile_client = ProfileClient()
    for row in rows:
        ok = profile.profile_broker(conn, row["id"], fetcher, profile_client)
        print(f"{row['domain']}: {'profiled' if ok else 'no articles found'}")
    return 0
```

Wire into `main`'s subparsers alongside the existing commands:
```python
    p_profile = sub.add_parser("profile")
    p_profile.add_argument("--limit", type=int, default=MAX_PROFILE_CALLS)
```
and in the dispatch chain:
```python
    if args.command == "profile":
        return cmd_profile(args.db, args.limit)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS — all prior tests plus 5 new.

Note `test_profile_at_the_ceiling_is_allowed` passes only because the database has no qualified brokers, so `Fetcher()` and `ProfileClient()` are never constructed and no key is needed. Confirm the early return happens before those constructions — if it does not, the test will try to build a real client. That ordering is load-bearing.

- [ ] **Step 5: Commit**

```bash
git add src/bce/cli.py src/bce/discover.py tests/test_cli_profile.py
git commit -m "feat: bce profile command with spend ceiling"
```

---

## Self-Review

**1. Spec coverage.** Stage 3 (§5) → Tasks 1–5. §10.3 never-store-full-text → Tasks 1, 3, 5 (`test_stores_quotes_as_json_and_never_the_article` is the guard). §10.2 crawling → Task 1 (all fetching via the existing `Fetcher`; the bound is checked before fetching). §11.5 API ceiling → Task 6. Model and structured-output correctness → Task 4.

**Deliberate gaps, not omissions:**
- Stage 4 (angles, drafting, dual format, the three originality gates) — next plan. The six `draft` columns and `draft_asset` from §8 belong there, added through `db.ADDITIVE_COLUMNS`.
- Playwright (§7) — still absent, so SPA blogs yield shells and `collect_articles` returns nothing for them. That is recorded in `FOLLOW-UPS.md` and now bites harder: an SPA broker qualifies but cannot be profiled. Worth naming in the Stage 4 plan.
- Prompt caching — the system prompt is stable across brokers and could be cached, but at 20 calls the saving is negligible and a `cache_control` breakpoint is one more thing to get wrong. Deferred deliberately.

**2. Placeholder scan.** No TBDs. Every code step is runnable.

**3. Type consistency.** `collect_articles`/`extract_article_text` (Task 1) consumed in Task 5. `avg_sentence_length`/`typical_word_count`/`structure_pattern` (Task 2) and `select_quotes` (Task 3) consumed in Task 5. `ProfileClient.classify` (Task 4) consumed in Task 5 — and Task 5's `FakeProfileClient` implements exactly that one-method surface. `unprofiled_brokers` (Task 6) matches the `voice_profile` columns Task 5 writes. `PROFILE_SCHEMA`'s four properties are exactly the four keys Task 5 reads via `.get()`.

**4. Pressure tests planted deliberately.** This is the section the last plan lacked, and its absence cost five fix rounds. Three known traps are called out inline for the implementer to resolve rather than trip over:
- **Task 2 contains a wrong expected value on purpose.** `avg_sentence_length` on the abbreviation fixture yields 13, not the 11 the test asserts, because `_WORD` splits `24.5` into `24` and `5`. The implementer must reconcile it and report which side they changed. Left in because a hand-computed expectation that disagrees with the implementation is exactly the class of defect this project kept shipping.
- **Task 4 requires verifying the `anthropic` exception hierarchy** rather than assuming `APIConnectionError` is an `APIError` subclass — the same assumption about `httpx.InvalidURL`/`httpx.HTTPError` was wrong earlier and would have halted a crawl.
- **Task 5's §10.3 guard may not discriminate** if the chosen fixture sentence is under the 200-char cap. The implementer must confirm it fails when the cap is removed, and pick a longer sentence if not.

**5. Known weakness.** `_SENTENCE_END` requires a capital letter after the terminator, which is what protects `approx. 24.5 m` — but it means a sentence starting with a lowercase word or a numeral is silently joined to its predecessor. That inflates `avg_sentence_length` on copy that opens sentences with figures ("60 ft is the threshold..."). Acceptable for a register signal, wrong for anything precise. Named here rather than discovered later.
