# Drafting Engine Implementation Plan (Stage 4a)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For a profiled broker, generate candidate article angles, pick the best, and draft it in that broker's register — in two formats: a long form for their blog and a short form for their newsletter.

**Architecture:** Three LLM steps (angles → long draft → short condensation), each behind an injectable client so the suite runs offline. A structure fix lands first because drafting conditions on paragraph shape and that statistic is currently always `1`. Drafts persist to the existing `draft` table, extended additively.

**Tech Stack:** Python 3.11.9, anthropic SDK (`claude-opus-5`), selectolax, sqlite3, pytest

**Spec:** `docs/superpowers/specs/2026-08-20-broker-partner-content-design.md` (v0.5) — §3, §5 Stage 4, §8, §10.3, §11.5

## Scope — what this plan does NOT build

**The three originality gates (§10.3) are Stage 4b, not this plan.** Uniqueness by embedding similarity, the tailored/register score, and the near-duplication check against source prose all come next. Also deferred: the editorial value test (§3), Sunreef fact verification (§10.4), and `AssetProvider` (§7, Dropbox is still weeks out).

**This matters and must be stated in the UI when drafts are displayed:** a draft produced by this plan is an *unvetted artifact*. Nothing may be sent to a broker until Stage 4b's gates and Stage 5's human review exist. Drafts here are for looking at, not for using.

## Global Constraints

- **Model is `claude-opus-5`.** Structured outputs via `output_config={"format": ...}`; `output_format` is deprecated. Do not pass `budget_tokens` — rejected on Opus 5.
- **Every LLM client is injectable and lazily constructed.** No test may require an API key or touch the network. 287 tests currently hold that property.
- **Any API failure degrades, never raises.** A drafting run over 20 brokers cannot die on one call.
- **`MAX_DRAFT_CALLS = 10`** — a hard ceiling (§11.5). Each broker costs **three** calls (angles, long, short), so 10 brokers is 30 calls. Refuse above the ceiling; do not truncate.
- **The short form is a condensation of the long form, not a separate piece** (§5 Stage 4). Same angle, same claims, same voice. It is generated *from* the long draft, not from the brief.
- **Never store a broker's prose** (§10.3). Drafts are original output; the voice profile's capped quotes are the only source text in the system and that stays true.
- **No draft may reach `status = 'sent'`** — the schema forbids it without a human in `reviewed_by`, and no code in this plan writes that status.
- Python 3.11.9. No new dependencies.

---

### Task 1: Recover paragraph structure

**Files:** Modify `src/bce/articles.py`, `src/bce/style.py`; Test `tests/test_style_structure.py`

**Why first:** `structure_pattern` currently reports `{"paragraphs_per_article": 1, ...}` for every real broker, because `trafilatura.extract` returns paragraphs joined without newlines. Verified: a three-`<p>` article extracts to one unbroken line, and neither `include_formatting=True` nor `output_format="markdown"` changes it. `words_per_paragraph` therefore degenerates into a duplicate of `typical_word_count`.

Drafting conditions on structure. Fixing it here is the decision the Stage 3 follow-ups asked for.

**Verified:** `HTMLParser(html).css("p")` recovers 3 paragraphs where trafilatura gives 1. selectolax is already a dependency.

**Interfaces:**
- `articles.extract_paragraphs(html: str) -> list[str]` — paragraph texts from `<p>` nodes within the article body, boilerplate stripped, empties dropped
- `articles.collect_broker_articles` gains a parallel return of paragraph lists, OR `style.structure_pattern` accepts `list[list[str]]`. **Your design call** — state which and why. The constraint is that `avg_sentence_length` and `typical_word_count` must keep receiving flat text, since they are correct today.

- [ ] **Step 1: Write the failing test**

`tests/test_style_structure.py`:
```python
from bce.articles import extract_paragraphs

ARTICLE = """<html><body><article>
<p>Beam matters more than length when the marina is full in August.</p>
<p>Draft is the constraint nobody mentions until it is far too late.</p>
<p>Guests notice steadiness at anchor long before they notice speed.</p>
</article></body></html>"""


def test_recovers_paragraphs_trafilatura_flattens():
    import trafilatura
    flat = trafilatura.extract(ARTICLE)
    assert len([p for p in flat.split("\n") if p.strip()]) == 1, "premise: trafilatura flattens"
    assert len(extract_paragraphs(ARTICLE)) == 3, "selectolax must recover them"


def test_drops_empty_paragraphs():
    assert extract_paragraphs("<article><p>Real text here.</p><p></p><p>  </p></article>") == [
        "Real text here."
    ]


def test_excludes_nav_and_footer_paragraphs():
    html = ("<body><nav><p>Home</p></nav><article><p>The actual article body text.</p>"
            "</article><footer><p>Copyright</p></footer></body>")
    paras = extract_paragraphs(html)
    assert paras == ["The actual article body text."]


def test_handles_a_page_with_no_paragraphs():
    assert extract_paragraphs("<html><body><div>no p tags</div></body></html>") == []
```

- [ ] **Step 2: Run to verify failure.** `ImportError: cannot import name 'extract_paragraphs'`.
- [ ] **Step 3: Implement.** Strip `nav`/`header`/`footer`/`aside`/`script`/`style` first — reuse the existing `_markup_without_code`/`strip_tags` approach in `detectors.py` rather than inventing a second one. Then collect `<p>` text.
- [ ] **Step 4: Run the full suite.** Existing `structure_pattern` tests will change — **name each one you change and why.** Then report what `structure_pattern` now returns for a real multi-paragraph article versus what it returned before.
- [ ] **Step 5: Commit** — `fix: recover paragraph structure that trafilatura flattens`

---

### Task 2: Draft schema

**Files:** Modify `src/bce/db.py`; Test `tests/test_db_draft.py`

**Interfaces:** Extend `ADDITIVE_COLUMNS` with the `draft` columns from §8: `format TEXT`, `passes_uniqueness INTEGER`, `max_similarity REAL`, `most_similar_draft_id INTEGER`, `passes_originality INTEGER`, `embedding TEXT`. Add the `draft_asset` table. Bump `SCHEMA_VERSION` to 2.

The four gate columns are written by Stage 4b, not this plan — they exist now so the migration path is already correct when 4b lands. `draft_asset` likewise (§7's Dropbox is weeks out).

`format` is the one this plan writes: `'long'` or `'short'`, with a CHECK constraint.

- [ ] **Step 1: Write the failing test** — assert the six columns and `draft_asset` exist after `init_schema`; assert an old-shape database gains them (the migration path Stage 1–2 built); assert `format` rejects a value outside `('long','short')`.
- [ ] **Step 2–5** as usual. Commit: `feat: draft schema for dual-format drafting`

---

### Task 3: Angle generation

**Files:** Create `src/bce/angles.py`; Test `tests/test_angles.py`

**Interfaces:**
- `ANGLE_SCHEMA` — structured output: a list of 3–5 angles, each `{title, premise, audience_value, sunreef_relevance, score}` with `score` 0–1
- `class AngleClient(client=None)` with `propose(profile: dict, broker_name: str) -> list[dict]`; returns `[]` on any failure
- `best_angle(angles: list[dict]) -> dict | None` — highest score, `None` for an empty list

**The prompt must carry the voice profile**, so angles suit this broker's audience rather than being generic. The `audience_value` field exists because §3's hard question is *why would this broker publish this* — an angle that cannot answer it is not a candidate.

**Semrush is NOT wired in this task.** Keyword research would genuinely improve angle selection — it tells us what a broker's audience actually searches for, which makes content more useful to them and strengthens the pitch. But its response shape has not been verified against the live API, and building against an unverified shape is how the `httpx.InvalidURL` class of defect happens. Define the seam — `AngleClient(..., keyword_source=None)` with a null default — and leave wiring it to a follow-on once we have seen one real response.

- [ ] Steps as usual. Include a test that `propose` makes no API call for an empty profile, and one that a malformed response yields `[]`.
- [ ] Commit: `feat: angle generation scored against the voice profile`

---

### Task 4: Long-form drafting

**Files:** Create `src/bce/draft.py`; Test `tests/test_draft_long.py`

**Interfaces:**
- `class DraftClient(client=None)` with `write_long(angle: dict, profile: dict, broker_name: str) -> str | None`
- Returns `None` on any failure

The prompt conditions on the profile's `register`, `typical_word_count`, `structure_pattern` (now real, per Task 1), `vocabulary_markers`, and `sample_quotes`. Target length is the broker's own `typical_word_count`, not a fixed number — §5 says "matched to their typical word count."

**Two constraints the prompt must carry**, because they are spec requirements and not stylistic preferences:
- Sunreef appears as **one example among several** where genuinely relevant, never as the subject (§3).
- **No competitor disparagement** — Lagoon, Fountaine Pajot, and Catana are never named against (§2).

- [ ] Steps as usual. Test that the request carries the broker's word count, that a refusal yields `None`, and that no API call is made without an angle.
- [ ] Commit: `feat: long-form drafting in the broker's register`

---

### Task 5: Short-form condensation

**Files:** Modify `src/bce/draft.py`; Test `tests/test_draft_short.py`

**Interfaces:** `DraftClient.write_short(long_body: str, profile: dict) -> str | None` — 100–200 words plus a headline.

**This is the constraint that matters:** the short form is generated **from the long draft**, not from the angle. §5 says "a condensation of the long form, not a separate piece: same angle, same claims, same voice." Two independent generations would drift, and a broker publishing both would look incoherent.

**Plant a test that proves it:** call `write_short` with a long body containing a distinctive factual claim, and assert that claim survives into the short form. A short form generated from the brief instead of the body would not carry it.

- [ ] Steps as usual. Commit: `feat: newsletter-length condensation from the long draft`

---

### Task 6: Orchestrator and persistence

**Files:** Create `src/bce/drafting.py`; Test `tests/test_drafting.py`

**Interfaces:** `draft_for_broker(conn, broker_id, angle_client, draft_client) -> DraftResult` — loads the voice profile, proposes angles, picks the best, writes both formats, persists two `draft` rows (`format='long'` and `'short'`) linked to one `angle` row.

Mirror Stage 3's `ProfileResult`: a frozen dataclass with `__bool__`, because a NamedTuple's truthiness would silently break `is False` — that exact trap was caught in Stage 3.

**Behaviours to get right:**
- A broker with **no voice profile** writes nothing and makes no API call.
- Empty angles → nothing written, no further calls.
- A `None` long draft → nothing written, and **no short call attempted** (it has nothing to condense).
- A `None` short draft with a good long draft → **the long row is still written**, and the result reports the short one failed. Losing a good long draft because the condensation failed would be waste.
- Both rows carry `status='pending_review'`. Nothing writes `'sent'`.

- [ ] Steps as usual. Commit: `feat: drafting orchestrator with dual-format persistence`

---

### Task 7: CLI with spend ceiling

**Files:** Modify `src/bce/cli.py`, `src/bce/discover.py`; Test `tests/test_cli_draft.py`

**Interfaces:**
- `discover.undrafted_brokers(conn, limit)` — profiled brokers (with a `voice_profile` row) that have no `draft` yet
- `cli.MAX_DRAFT_CALLS = 10`, `cmd_draft(db_path, limit=MAX_DRAFT_CALLS)`

**The ceiling check must precede any client construction**, and must reject `limit < 1` as well as `limit > MAX_DRAFT_CALLS` — SQLite treats a negative `LIMIT` as unbounded, and that exact bypass shipped in Stage 3 before a whole-branch review caught it. Test `-1` and `0` explicitly.

Each broker costs three calls. Say so in the refusal message so the operator understands the ceiling is brokers, not calls.

- [ ] Steps as usual. Commit: `feat: bce draft command with spend ceiling`

---

## Self-Review

**1. Spec coverage.** §5 Stage 4 angles/drafting/dual-format → Tasks 3–6. §8 draft columns → Task 2. §11.5 ceiling → Task 7. The Stage 3 follow-up on paragraph structure → Task 1.

**Deliberately deferred, stated in Scope above:** §10.3's three gates, §3's editorial value test, §10.4 fact verification, §7's `AssetProvider`, and Semrush wiring. Each is named with a reason rather than silently absent.

**2. Placeholder scan.** No TBDs. Tasks 2 and 4–7 give interfaces and behaviours rather than full code — deliberate, because the LLM-call shape is established by Tasks 3's example and repeating it four times would invite copy-paste drift. Every task names its exact interfaces and the behaviours its tests must prove.

**3. Type consistency.** `AngleClient.propose` (Task 3) → `best_angle` → `DraftClient.write_long` (Task 4) → `write_short` (Task 5) → `draft_for_broker` (Task 6) → `cmd_draft` (Task 7). `DraftResult` mirrors Stage 3's `ProfileResult` including the `__bool__` requirement.

**4. Pressure tests planted deliberately.**
- **Task 1 asserts the premise before the fix** — `test_recovers_paragraphs_trafilatura_flattens` first asserts trafilatura really does flatten to 1. If that premise ever stops holding, the test says so rather than silently passing.
- **Task 5's distinctive-claim test** is the only thing that can distinguish a genuine condensation from an independent second generation. Without it, "the short form derives from the long form" is an untestable claim.
- **Task 7 requires testing `-1` and `0`** because the identical negative-limit bypass shipped in Stage 3.
- **Task 6 requires a frozen dataclass, not a NamedTuple**, naming the truthiness trap that caught Stage 3.

**5. Known weakness.** Three LLM calls per broker means a failure mid-sequence leaves partial work. Task 6 handles the long-succeeds/short-fails case explicitly, but a broker whose angle call succeeds and long call fails has spent one call for nothing. Acceptable at a 10-broker ceiling; worth revisiting if the ceiling rises.
