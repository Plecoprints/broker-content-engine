# Follow-ups from the voice-profiling plan (Stage 3)

Carried out of the SDD workspace before it was deleted. Ordered by what the Stage 4 plan must decide.

## Must be decided in the Stage 4 plan

### 1. `paragraphs_per_article` is structurally always 1 — the *Tailored* gate has nothing to score

`style._PARA_SPLIT` splits on blank lines, but `trafilatura.extract` returns paragraphs **joined without
newlines at all**. Verified: a three-`<p>` article extracts to one unbroken line. Neither
`include_formatting=True` nor `output_format="markdown"` changes it.

Consequences:
- `paragraphs_per_article` is `1` for every real extraction.
- `words_per_paragraph` therefore degenerates into a duplicate of `typical_word_count`.

This matters because spec §10.3's *Tailored* gate is specified to score "register/structure match" as a
blocking check in Stage 4 — and there is currently no structure to match against.

Not fixed here because no finding covered it and the fix changes a statistic Stage 4 will consume; it
needs a decision, not a patch. Options: extract paragraphs with selectolax over `<p>` nodes instead of
trafilatura's flattened text, drop the paragraph dimension and keep only `words_per_paragraph` measured
some other way, or drop structure from the *Tailored* gate and score register alone.

### 2. `structure_pattern` has no migration path

Values are now `json.dumps({"paragraphs_per_article": N, "words_per_paragraph": M})`. Any row written
before that change holds prose (`"3 paragraphs/article, 42 words/para"`) which raises `JSONDecodeError`,
and bulk `bce reprofile` cannot reach it because bulk mode only clears rows whose `register IS NULL`.

Parked because **no operator database exists yet** — verified, nothing to migrate. If a pilot DB is
built before Stage 4 lands, either widen bulk `clear_voice_profile` to also clear rows whose
`structure_pattern` does not parse, or migrate in `db.init_schema`.

## Should be fixed when convenient

### 3. Two definitions of "warmest first"

`bce list` uses `discover._AFFINITY_RANK` (`unknown` 2, `none` 3). `bce profile` uses `_AFFINITY_ORDER`,
which collapses both to the same rank. With Zeta/`unknown` and Alpha/`none`, `bce list` prints
`[zeta, alpha]` and `bce profile` processes `[alpha, zeta]` — two sources of truth for one §4 policy.

Ordering-only and no broker is ever excluded, so nothing is unfair — it is an inconsistency, not a
tiering breach. Fix by deriving the SQL `CASE` from `_AFFINITY_RANK`.

### 4. `MAX_FIELD_CHARS` / `MAX_LIST_ITEMS` are duplicated literals

`llm.py` and `profile.py` each define 120 and 8 independently, with no test binding them. They agree
today; nothing stops them drifting. The schema value is a request to the model, the `profile.py` value
is the enforcement — if they diverge, the clamp silently stops matching what the schema promised.

## Accepted trade-offs — recorded so they are not re-litigated as bugs

- **No minimum-one quote guarantee.** A corpus too thin to quote from stores zero quotes rather than one
  over-large one. The zero-quote regime is below ~450 characters, which real articles never reach — an
  800–1500 char post still yields 1–2 quotes. **Do not loosen `MAX_RETAINED_FRACTION` in response to
  seeing empty `sample_quotes`**: during this plan, empty quotes were a symptom of profiling index pages,
  not of the cap being too tight. The cap acted as an accidental smoke alarm and was briefly mistaken
  for the fire.
- **Chrome links may be fetched on pages with no `<main>` and no `<nav>`.** They are same-host pages that
  fail the 600-char floor, so they cost a bounded number of requests and never reach the statistics.
  Tightening further would require a path blocklist — the classifier this design deliberately avoids.
- **Truncation for the API lives in `llm.py`, not `articles.py`.** The deterministic statistics keep the
  full text, because `typical_word_count` is precisely what Stage 4 drafts against (§5). Capping before
  measurement would trade an unbounded-cost bug for a wrong-number bug. Only what is *sent* is bounded:
  `MAX_CLASSIFY_CHARS_PER_ARTICLE = 4000`, `MAX_CLASSIFY_CHARS = 20000`.
- **`collect_articles` has no production caller** — the single-level primitive is kept exported and tested
  beside the two-level `collect_broker_articles`. Worth a docstring warning; re-wiring `profile.py` to it
  would reintroduce the Critical this plan spent two rounds closing.
- **Playwright remains absent** (spec §7 lists it). A JS-rendered journal yields no extractable text, the
  broker is skipped with "no articles found", and the CLI says so. Graceful and visible; §12 already
  names manual profiling as the accepted fallback.

## Shippable minors (11, all triaged SHIP by the whole-branch review)

No test drives `extract_article_text` → `""` and the `if text:` skip. The empty-body fixture lacks a
comment explaining why it is empty rather than boilerplate-only (trafilatura extracts nav text, so an
empty body is the only reliable `None` trigger). No test exercises a style function with more than one
text. Sentences opening with a lowercase word or a numeral join to the predecessor. The ranking test
closes the first-N loophole but not last-N. No small-fixture test of ranking or truncation. The JSON-list
non-dict variant is untested; only `None` is covered. `test_unreachable_homepage_writes_nothing` asserts
`calls == 0` but not row count. `profile_broker` does not guard `row is None` for a nonexistent
`broker_id`. `ORDER BY` is untested with more than one qualifying result. `cmd_profile`'s loop has no
error handling — self-healing in practice, since the existence check means committed brokers are skipped
on re-run and nothing is double-billed.

Two further nits: exhausting the post budget breaks only the inner loop, so up to two more index pages
are fetched for nothing (bound still holds). And the "13 requests/broker" comment in `articles.py` omits
`profile_broker`'s homepage fetch — the real figure is 14.
