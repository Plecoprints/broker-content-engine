# Follow-ups from the shortlist-pipeline plan

Carried out of the SDD workspace before it was deleted. Ordered by what I would fix first.

## FIXED (2026-08-21)

Items 1 and 2 below were fixed and reviewed clean. Summary of what landed:

- **Undeterminable editorial date** now has its own reason `editorial_recency_undetermined`, and a
  stale-but-dated channel has a third reason `editorial_stale` — a broker with a dormant journal is no
  longer told they have no channel. `_editorial_recency` tries up to 3 editorial URLs, returns early
  only on a *fresh* date, and otherwise records the **most recent** date found (real `date`
  comparison, not string ordering). One fetch when the first URL dates cleanly. `cmd_list` now prints
  `editorial=`, `last_post=`, `newsletter=`.
- **Newsletter email co-signal** is DOM-scoped: the subscribe word and the `<input type="email">` must
  sit inside the same `<form>` node's own subtree. The first attempt used a regex block match, which a
  reviewer proved reopened the same defect — a lazy `.*?</section>` spans everything nested inside a
  broad wrapper. `<section>` was dropped as a container for exactly that reason.

165 tests. Two cosmetic items came out of that review and remain open:

- `test_cookie_banner_and_email_input_under_shared_div_ancestor_does_not_count` does not discriminate
  the fix it is named for — the old regex never matched `<div>`, so it passed before and after. It
  documents correct behaviour but guards nothing. Rewrite it around a `<section>` or `<form>` ancestor.
- `_form_evidence` builds a third `HTMLParser` tree per page (after `_markup_without_code` and
  `find_editorial_urls`). Only reached when cheaper checks miss; note if throughput ever matters.

## Was required before the shortlist is trusted unattended — now fixed, kept for the record

These two distort qualification on realistic broker markup. They do **not** block spec §13's manual
pilot (one hand-picked broker), which is the intended next step.

### 1. Undeterminable editorial date silently rejects viable brokers — fix first

`qualify.py` treats "no publication date found" as "no editorial channel", which is the right
conservative default, but the mechanics around it are wrong three ways:

- The rejection is recorded as `no_publishing_channel` — the same class of misleading `reason` the
  recency work was filed to remove. It needs its own value, e.g. `editorial_recency_undetermined`.
- No CLI command surfaces `editorial_last_post`, so an operator cannot tell "we could not date it"
  from "there is no channel".
- Only `editorial_urls[0]` is dated. `find_editorial_urls` returns DOM order, so a nav reading
  `Guides | Blog` dates the evergreen `/guides` page and never looks at the blog.

Estimated impact: a fifth to two-fifths of editorial-only brokers silently rejected — material
against a working set of 20. Fix: own reason string, try 2–3 editorial URLs, surface the column in
`cmd_list`.

### 2. Newsletter email co-signal is page-global

`detect_newsletter` gates `subscrib*` behind an email co-signal, but `has_email_input` is computed
over the whole body and short-circuits the proximity window. Since an `<input type="email">` is
near-universal (contact form) and footers routinely carry a social "Subscribe", the false positives
return in combination:

```
"Subscribe to our YouTube channel" + <input type=email> elsewhere  -> has_newsletter = 1
cookie banner "subscribe or unsubscribe anytime" + email input     -> has_newsletter = 1
```

A newsletter alone qualifies a broker (spec §4), so this inflates the shortlist. Strictly narrower
than the original defect (bare `subscribe` qualified unconditionally), so not a regression. Fix
(~5 lines): require the email input inside the proximity window or the same `<form>`/`<section>`.

## Parked — reachable only after a first real import

### 3. Domain normalization never reaches stored rows

Import-time normalization is correct, but nothing normalizes `broker.domain` for rows already in the
database, and `qualify_broker` interpolates the stored string verbatim. On a database created before
this fix, a cell of `https://acme.com/` still builds `https://https://acme.com//`, is permanently
rejected, and `bce requalify <domain>` cannot find it because it normalizes its argument but matches
the raw column.

Parked because **no database exists yet** — verified, nothing to migrate. Fix alongside the next
plan's own additive columns: one-time `UPDATE broker SET domain = normalize_domain(domain)` with
collision handling, or normalize at read time.

## Spec constraints to carry forward

- **§10.2 should state that redirect targets must be public IPs.** The SSRF restriction was shipped as
  Minor for this branch (operator-curated input, GET only, no egress channel). Three scheduled changes
  flip it to Important: automated discovery (untrusted domains), any unattended execution, and the
  **localhost operator UI — the next plan** — which makes `http://localhost:8000` the most attractive
  redirect target on the machine. Fix belongs in the discovery plan, gated by a spec line rather than
  by memory.
- **§8's `draft` table ships incomplete** — missing `format`, `passes_uniqueness`, `max_similarity`,
  `most_similar_draft_id`, `passes_originality`, `embedding`, and `draft_asset` entirely. Deliberate;
  the additive-migration path in `db.py` exists to add them.
- **§4's "operates in Sunreef's markets" is unimplemented.** `region` is imported as free text and read
  by nothing. Of three machine-checkable criteria, two are enforced. Deferred by accident, not design.
- **§7's Playwright is absent.** SPA homepages are judged on their pre-JS shell. Combined with the
  newsletter detector, an SPA broker who *does* have a blog can be recorded `has_editorial=0,
  has_newsletter=1` — which would tell Stage 4 to write the short newsletter form for a broker with a
  blog and no newsletter.
- **§5 Stage 1's automated half is unbuilt.** `source='discovered'` is a dead enum; discovery is CSV
  import only.

## Shippable minors (23, triaged SHIP by the whole-branch review)

Cosmetic or report-only: `SCHEMA_TABLES` type annotation; missing docstrings on `connect`/`init_schema`.

Affinity detector quality — all bounded by the ordering-only invariant, so a wrong level reorders a
list and nothing else: naive substring markers (`"priceless"` matches `price`); post-match-biased
evidence window; missing multi-mention and substring tests.

Editorial detector: `/guide` singular never matches the `guides` hint (the hint tuple mixes singular
and plural under a shared `s?`, so coverage is accidental — normalize to singular with `(?:s|es)?`);
O(n) dedup scan.

Fetcher: unthrottled robots.txt fetch (one extra request per host, once); no response size cap on the
page fetch (timeout bounds duration, not payload); cookie jar persists per `Fetcher` lifetime;
`robots_allowed=1` recorded when a redirect *target* was disallowed; `USER_AGENT` points at the
Sunreef homepage rather than a `/bot` or `mailto:` contact a blocked webmaster could write to.

CLI: `cmd_list` prints only name/domain/affinity/state, so `qualified_reason` and the three evidence
columns are written and read by nothing; `SchemaTooNewError` uncaught in all four commands; errors
print to stdout while one path uses stderr; `main([])` prints "unknown command" rather than help;
`python -m bce.cli` is a no-op (no `__main__` block) — the `bce` console script is the entry point;
DB connections never closed.

Tests: `test_length_from_visible_text_ignores_attribute_and_script_numbers` asserts
`detect_max_length_ft(RAW_HTML) == 300`, pinning known-buggy regex behaviour — any later tightening
fails a test on an improvement; the quoted-newline CSV test does not exercise the cap-counting path
its docstring claims (needs a fixture on the cap boundary); `parse_rows` runs three times per import.
