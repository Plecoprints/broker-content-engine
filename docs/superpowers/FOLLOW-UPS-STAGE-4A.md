# Follow-ups from the drafting-engine plan (Stage 4a)

## Must be decided in Stage 4b

**The three originality gates are not built.** §10.3's uniqueness (embedding similarity, scoped within
format), tailored (register/structure match), and originality (near-duplication vs source prose) checks
all belong to 4b, along with §3's editorial value test and §10.4 Sunreef fact verification. Until they
exist, **a draft is an unvetted artifact** — nothing writes `status='sent'`, everything lands
`pending_review`, and no code path sends anything to a broker.

**`_BaseClient` refactor.** Three LLM clients (`llm.ProfileClient`, `angles.AngleClient`,
`draft.DraftClient`) now duplicate the same ~15 lines: lazy construction, `except anthropic.APIError`
degradation, the refusal check, and text extraction. The whole-branch review made the case that the
third copy is where this stops being premature — the `max_tokens` fix had to be reasoned about in three
places. Deliberately not done in a fix wave, since it touches all three at once.

**Input bounds are transitive, not stated.** `ProfileClient` bounds its untrusted input explicitly
(`MAX_CLASSIFY_CHARS`); `AngleClient` and `DraftClient` bound nothing. In practice both are bounded —
profile fields are clamped at persist, `sample_quotes` by `MAX_QUOTES`/`MAX_QUOTE_CHARS`, `long_body` by
`MAX_TOKENS_LONG`. So no unbounded path exists, but nothing says so, and a field added to
`_profile_summary` would break it silently.

## Semrush — the seam exists, the wiring does not

`AngleClient(client=None, keyword_source=None)` is the seam. Keyword research would genuinely improve
angle selection — knowing what a broker's audience searches for is what makes an article worth their
publishing, which is exactly §3's editorial value test. The distinction that must hold: **Semrush informs
what we write about, never how we write it.** Topic selection strengthens the content; keyword
optimisation re-imports the ranking-manipulation framing §1 deliberately walked away from.

Not wired because the live response shape has not been seen once. Building against an unverified shape
is how the `httpx.InvalidURL` defect shipped. One real call resolves it.

## Shippable minors (triaged SHIP by the whole-branch review)

`test_keyword_source_defaults_to_none_and_is_not_called`'s first assertion is vacuous.
`test_schema_bounds_list_length` is tautological. `style._PARA_SPLIT` is now dead in `src/` — its only
live use moved into a test. Unused `pytest` imports in both draft test files. `_draft_label`'s
short-failed branch has no CLI-level test. `test_draft_at_the_ceiling_is_allowed` documents a property
it does not check — the negative-limit test has the real `_boom` monkeypatch; the nothing-to-do path
deserves the same, since it is the path an operator hits on every re-run.

## Accepted trade-offs

- **A broker whose angle call succeeds but whose long draft fails has spent one call for nothing.** No
  partial-work compensation. Acceptable at a 10-broker ceiling; revisit if it rises.
- **`bce redraft` with no argument clears only degraded brokers** (long present, short missing) rather
  than re-drawing everything. Regeneration is a deliberate operator action, not automatic — §11.5
  budgets retries but does not authorise spending them silently.
- **`draft_asset` migration leaves old columns in place.** SQLite has no simple `DROP COLUMN`, nothing
  reads them, and the §8 columns are all present.
