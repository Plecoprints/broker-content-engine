# Broker Partner Content Engine — Design Spec

**Status:** v0.6 draft. Changes from v0.5, both decided by Luis on 2026-09-01: three draft formats instead of two — long is now a 2000–2300 word **pillar** article where voice matching is encouraged rather than binding, medium is the voice-matched regular post, short stays the newsletter form (§5 Stage 4, §8). And the backlink question is **settled and closed**: links are welcome if a broker chooses to give one, and are not a goal, not measured, and not designed for. Luis: *"if they do it great and if they don't we also still win."* §1's framing was already built for this; nothing in the design changes.

Changes from v0.4: newsletter recognised as a publishing channel in its own right — qualification now passes on editorial **or** newsletter (§4, §5 Stage 2); every draft is produced in long and short formats, the short one built for the broker's email newsletter (§5 Stage 4); uniqueness comparison scoped within format so an article does not flag as a duplicate of its own summary (§5, §10.3).

Changes from v0.3: originality split into three distinct checks with a corpus-wide uniqueness gate (§10.3); marketing asset library added as a deferred, interface-first dependency (§7, §11.3); Supabase evaluated and deferred with an explicit adoption trigger (§7).

Change from v0.2: Sunreef's dealer list is unavailable (IT), so the dealer/broker segmentation is removed. One shortlist, uniform treatment for everyone on it. A publicly-detectable Sunreef affinity signal replaces the dealer list for queue ordering only (§4). Remaining open decisions in §11.

**Goal:** Build a shortlist of yacht brokers operating in Sunreef's segment, understand each one's editorial voice and audience, and produce article drafts they genuinely want to publish — earning Sunreef qualified referral traffic.

**Owner:** Luis Perez, Sunreef
**Date:** 2026-08-20

---

## 1. Strategy: what this optimizes for

The original framing was a backlink automation tool. This spec changes the success metric, for a reason that is load-bearing rather than cosmetic.

**Why not backlinks.** Google's link spam policy treats links placed in guest content for ranking purposes as spam; the compliant markup is `rel="sponsored"` or `rel="nofollow"`, which passes no authority. Either brokers mark links correctly and link equity is zero, or they don't and both domains carry risk — with Sunreef, as the beneficiary, more exposed. Google's scaled content abuse policy separately targets mass-produced content made primarily to manipulate rankings.

**What this optimizes for instead.** Qualified referral traffic and broker relationships. A reader of a 60ft+ broker's blog is a pre-qualified prospect; reaching them through a trusted intermediary is distribution that does not depend on link attributes and does not decay with algorithm updates.

**Consequence of losing the dealer segment.** v0.2 led with Sunreef's dealer network, where publishing Sunreef content is ordinary co-marketing. That path is closed — the dealer list is not available. Everything below is therefore the harder case: content offered to independent businesses with no existing obligation to Sunreef. Two things follow, and both are treated as requirements rather than cautions:

1. **Legal review is blocking before any outreach** (§10.1), not just for a secondary segment.
2. **The editorial value test applies universally** (§3). It is now the single most important quality gate in the system.

## 2. Non-goals

Explicitly out of scope. Each is a way this project could fail badly:

- **No auto-publishing.** The system never publishes to a third-party site. It produces drafts.
- **No mass outreach.** Capped and human-sent (§6). This is not a mail-merge.
- **No link acquisition targets.** No quota of links, no anchor-text optimization, no link-placement negotiation.
- **No scraping behind logins, paywalls, or `robots.txt` disallow.** Public pages only.
- **No reproduction of broker content.** Voice analysis extracts stylistic features; it never copies source prose.
- **No competitor disparagement.** Content never positions against Lagoon, Fountaine Pajot, Catana, or others by name.
- **No tiered service.** Every broker on the shortlist receives the same pipeline, the same quality bar, and the same review scrutiny.

## 3. The hard problem

The engineering is straightforward. The hard problem is editorial:

> Why would this broker publish this?

A broker publishes what helps them sell yachts and serve clients. They will not publish a Sunreef advertisement. The system must produce content where **Sunreef appears as a credible example inside a genuinely useful article**, not as the subject of one.

Every draft must pass the **editorial value test**: *if every Sunreef mention were removed, would this still be worth publishing on this broker's blog?* If no, the draft is rejected. This is a hard gate, not a guideline, and it now applies to every draft without exception. Enforced as a gate in the §10.9 ensemble rather than by a reviewer's judgment (revised 2026-09-02).

## 4. The shortlist

One list. Everyone on it is treated identically.

**A qualifying broker:**

- Brokers or charters multihulls and/or yachts **≥60ft**
- Operates in Sunreef's markets (Mediterranean, Caribbean, UAE/Gulf, SE Asia, US East Coast)
- Has **at least one publishing channel**: an editorial section (blog/journal/news) updated within the last 12 months, **or** an email newsletter. Either qualifies.
- Passes human vetting in the UI

**Why newsletter counts as a channel.** A blog post has to be found; a newsletter goes directly to a list of people who chose to hear from that broker. For reaching qualified buyers it is the stronger channel, not a lesser one, so a broker with a newsletter and no blog is a viable target rather than a rejection. The two are detected separately and tracked separately — conflating them (matching `newsletter` with a blog-hint substring) was a real defect caught in review, and the fix was to separate them, not to discard the signal.

**Sunreef affinity signal.** During qualification the system records publicly observable evidence that a broker already has a Sunreef relationship — Sunreef vessels in their listed inventory, existing editorial mentions of the brand, shared yacht-show presence. This is a substitute for the unavailable dealer list, and its use is strictly limited:

- ✅ **Orders the review queue.** Warmest first, so the earliest outreach has the best chance of a yes.
- ✅ **Informs outreach wording** so a message never reads as cold to someone who already sells Sunreef.
- ❌ **Does not change** the pipeline, the quality bar, the editorial value test, or how much effort a broker's content receives.

Because the affinity signal is inferred from public pages, it will be incomplete. Any broker may turn out to have a Sunreef relationship the system cannot see, so **all outreach copy must be relationship-agnostic** — it has to read acceptably whether the recipient has never heard of Sunreef or has sold six of them.

## 5. Architecture

Seven stages. Stages 1–4 automated; **Stage 5 is a gate ensemble with operator sampling, operated through the UI (§9)** — revised 2026-09-02, see §10.9; 6–7 human-led with tooling support.

```
[1] Discover  →  [2] Qualify  →  [3] Voice Profile  →  [4] Angle + Draft
                                                              ↓
                                                    [5] HUMAN REVIEW GATE  ←── the UI (§9)
                                                              ↓
                                              [6] Outreach  →  [7] Measure
```

**Stage 1 — Discover.** Builds the candidate shortlist. Explicitly hybrid; the system does not pretend to find everything.

| Source | Coverage |
|---|---|
| Public directories, yacht-show exhibitor lists, charter marketplaces, search | Good for firms with a web presence |
| Sales/marketing knowledge, entered manually in the UI | High-value names no directory ranks |

Semrush (pending org approval) improves recall but is not a dependency.

**Stage 2 — Qualify.** Fetch public pages, confirm the ≥60ft criterion, detect **both** publishing channels independently (editorial section and email newsletter), and record the Sunreef affinity signal (§4). A broker passes on either channel; failing both is the rejection. Respects `robots.txt`, rate-limited, identifying User-Agent. Output: qualified/rejected with the evidence that drove the call, and which channels were found.

**Stage 3 — Voice Profile.** Extract published articles, derive a structured style profile: sentence length distribution, formality register, vocabulary markers, article structure, typical length, recurring themes, audience signals. **Stores derived features and short illustrative quotes only — never full article text.**

**Stage 4 — Angle + Draft.** Generate candidate angles scored against that broker's audience, then draft the highest-scoring angle in their register. The draft then passes the three originality gates (§10.3) before it may enter the review queue.

Every draft is produced in **three formats from one angle**:

| Format | Target | Shape |
|---|---|---|
| **Long** (pillar) | The broker's blog, as a cornerstone piece | **2000–2300 words.** A pillar article — comprehensive coverage of the topic. Voice matching is *encouraged but not binding*: at this length the piece serves depth first, and no broker's `typical_word_count` will be near it. |
| **Medium** | The broker's blog, as a regular post | **Matched to their `typical_word_count`** from the voice profile. This is the one that has to read like them — it sits alongside their own posts. |
| **Short** | The broker's email newsletter | Compressed — headline, 100–200 words, and a link back to the long or medium form where one will exist. Voice-matched. |

**Why long is the exception.** Voice matching and pillar length collide: a broker whose posts run 477 words will not publish a 2,200-word piece that reads nothing like their blog. So the long form is a *different product*, not a longer version of the same one — comprehensive by design, with the broker's register applied as far as it reasonably goes. Medium is the format that must genuinely pass as theirs.

**Medium and short are condensations of the long form**, not independent generations (same angle, same claims). Short may be condensed from medium where that reads better.

The short form is a condensation of the long form, not a separate piece: same angle, same claims, same voice. A broker with only a newsletter receives the short form as the primary deliverable, with the long form offered for their site if they want it.

**This changes the uniqueness gate.** Long and short versions of one article are near-identical by design, so §10.3's embedding comparison must be scoped **within format** — long against long, short against short. Comparing across formats would flag every article as a duplicate of its own summary.

**Stage 4b — Asset attachment (deferred).** Attach marketing-approved imagery from the asset library so the broker receives a publishable package rather than plain text. Behind an `AssetProvider` interface with a null implementation, so Stage 4 does not change when the real source lands (§7, §11.3). **Nothing blocks on this.**

**Stage 5 — Quality gate.** **Revised 2026-09-02 (§10.9): no longer a blocking human approval.** A draft must clear the §10.9 gate ensemble — six checks, every one failing closed — and the broker, who publishes or does not, is the human judgment on editorial fit. The UI remains, and the operator still sees the voice profile, the angle rationale and the draft, but now for **sampling**: reading a share of what shipped to detect gate drift, not approving each item. Sampling starts at 100% and steps down only as the gates earn it (§10.9).

**Stage 6 — Outreach.** Produces a personalized, relationship-agnostic message plus the draft, for a human to send. The system does not send email.

**Stage 7 — Measure.** **Revised 2026-09-02: measurement without attribution.** The earlier wording
here — "UTM-tagged links, referral traffic by broker, inquiries attributed to broker referral" —
contradicted §1, which settled and closed the backlink question: links are welcome if a broker chooses
to give one, and are **not a goal, not measured, and not designed for**. Sunreef supplies copy and
images for a partner to paste into their own channels; it does not publish on their behalf and does not
control the published URL, so there is nothing to tag and no click to attribute. A UTM convention would
have required asking for a link, which is the thing §1 decided not to do.

Three signals remain, and they measure what this system actually controls:

| Signal | Mechanism | What it tells you |
|---|---|---|
| **Collection** | `portal_event` — viewed / copied / downloaded (§9b) | Leading indicator: did the partner take it |
| **Publication** | Re-crawl the broker's editorial section (Stage 2 already does) and test shingle containment against drafts delivered to them (§9b) | The outcome. Works with no link, no tag, and survives the broker editing the piece — which they will, and should |
| **Return** | Does the broker come back next cycle and pick another angle | The strongest signal of value *to them*, and the one that predicts whether this compounds |

**What is deliberately not measured, so nobody re-adds it:** click-through, referral sessions, and
inquiries attributed to a broker. These are unavailable by construction, not by omission. The
consequence must be stated plainly wherever this programme is presented: **Sunreef cannot produce a
referral-ROI figure for this channel.** What it can produce is a count of partners publishing Sunreef
editorial under their own masthead, and whether they keep coming back.

`outcome`'s `utm_campaign`, `referral_sessions` and `inquiries` columns (§8) are consequently **never
populated**. They are left in place rather than migrated away: they cost nothing, and they are exactly
what would be needed if the §1 decision were ever reopened. Nothing should read them as data.

## 5b. Keyword targeting (Semrush)

Every draft is built around keywords the broker can realistically **win**, and both the operator and the
broker can see exactly which ones and why.

### Qualifying thresholds

A keyword may be baked into a draft only if:

- **Keyword difficulty < 30**, and
- **Average monthly search volume > 100**

Measured against real Semrush data for this niche, the thresholds are **selective but not scarce**. Some
obvious head terms do fail on difficulty — `sailing catamaran` (3,600, KD 41), `luxury yacht charter`
(8,100, KD 60), `yacht broker` (5,400, KD 78) — and a broker without Sunreef's domain authority would never
rank for them, so an article aimed there is an article wasted.

But the catamaran niche is **less contested than the surrounding luxury-yacht space**, and semantic
expansion surfaces high-volume terms that comfortably qualify: `catamaran for sale` (8,100, KD 25),
`catamarans for sale` (4,400, KD 24), `power catamaran for sale` (2,400, KD 17), `what is a catamaran`
(1,900, KD 25), `difference between a yacht and a sailboat` (2,400, KD 6). This is the strategic finding
behind the whole programme: **there is real, winnable search volume in catamarans specifically**, which is
exactly the category Sunreef occupies.

Both thresholds are **named constants, not literals**, and both are displayed in the UI so a broker
understands the standard their content is held to rather than taking it on faith.

### Editorial intent only

Decided 2026-09-01. The content this engine produces is **editorial, not commercial**. A keyword is
eligible only if its Semrush intent includes `Informational` and includes neither `Transactional` nor
`Navigational`.

- `Transactional` means the searcher wants to buy now. That is a product page, not an article, and an
  article aimed there reads as a sales sheet — which is precisely the thing a broker will not publish
  under their own masthead.
- `Navigational` means the searcher wants one specific brand or site. There is nothing editorial to write.
- **`Commercial` is retained.** Commercial-investigation intent is comparison and consideration content —
  `power catamaran vs sailing catamaran` (KD 2), `sailing monohull vs. catamaran` (KD 3), `catamaran cost`
  — which is the most editorial material in the entire bank. Excluding it would cost ~4,280 monthly
  searches for no benefit.

Measured against the operator's 243-keyword export, this rule is **nearly free**: of the 153 keywords that
survive the relevance gate, it removes exactly **one** — `solar powered catamaran` (480, KD 21). Its
near-synonyms `solar catamaran` (480, KD 23) and `electric catamaran` (390, KD 20) are pure-informational
and survive, so the Sunreef Eco cluster stays intact.

That the rule costs one keyword is the evidence that it is the right rule, not an argument that it does not
matter: transactional intent and off-target subject matter turned out to be almost the same set. Eleven of
the twelve transactional keywords in the export were already excluded as off-segment — rugs, inflatables,
tourist day-trips.

### Approved and excluded banks

Decided 2026-09-02. The operator curates the bank by hand, and that curation — not any threshold in
this section — is the authority on what may be written about.

Two committed files, together the whole 243-keyword export this section was written against:

| File | Rows | Role |
|---|---|---|
| `data/keywords-approved.csv` | 148 | **The only source.** Nothing is drafted against a phrase absent from it |
| `data/keywords-excluded.csv` | 95 | **A blocklist.** Never selectable, whatever its metrics |

Loaded with `bce keywords data/keywords-approved.csv` and `bce exclusions data/keywords-excluded.csv`.

**The blocklist is a fifth gate, and it lives in its own table.** The four gates above
(`qualifies`, `segment_relevant`, `editorial`, `competitor_brand`) are all *derived from metrics*, so
every one of them is recomputed by the next import — which means any of them can flip back to passing
when Semrush re-measures. `excluded_keyword` records a human decision instead, so it must outrank them
and survive those re-imports. `catamaran club` is the worked example: excluded by hand as `other_brand`,
yet 1,000 volume at KD 20 clears every automatic gate. Only the blocklist stops it.

Matching is casefolded and whitespace-collapsed. A blocklist that failed open on `"  Racing  CATAMARAN "`
would be worse than none, because it would look like it was working.

**The banks corroborate this section rather than contradicting it.** All 148 approved rows clear
KD < 30 and volume > 100; all 148 pass segment relevance; all 148 are editorial intent. The two files do
not overlap. And the single keyword the operator excluded for intent rather than segment —
`solar powered catamaran` (480, KD 21) — is exactly the one this spec predicted the intent rule would
remove. Exclusion reasons, for the record: `wrong_size_class` 32, `excursion_tourism` 31, `not_a_boat` 11,
`racing` 8, `other_brand` 7, `non_english` 5, `not editorial intent` 1.

`data/keyword_bank.sample.csv` (formerly `keyword_bank.csv`) is a fixture for tests and importer
development. It is **not** the operator's bank and must never be imported into a working database.

### Competitor brand terms

Semantic expansion surfaces competitor brand names that pass both filters — `lagoon catamaran` (2,400,
KD 26), `leopard catamaran` (1,000, KD 13), `aquila boats` (1,900, KD 22). These are Sunreef's direct
rivals. Ranking a partner broker for them is a defensible comparison play and a genuinely bad idea by
turns, and it is **not a call the engine should make silently**. A named brand-exclusion list gates them;
anything on it requires an explicit human decision before it can be baked into a draft.

### Keywords per format

Keyword load scales with length — roughly **one keyword per 500 words**. Four keywords in a 150-word
newsletter blurb is keyword stuffing, and it reads like it.

| Format | Primary | Secondary |
|---|---|---|
| **Long** (2000–2300 words) | 1 | up to 4 |
| **Medium** (their typical length) | 1 | up to 2 |
| **Short** (100–200 words) | 1 | 0 |

Because medium and short are condensations of the long draft (§5 Stage 4), their keywords are a **subset**
of the long draft's. A keyword appearing in the short version but not the long one would mean the
condensation introduced a claim the pillar never made.

### Provenance and staleness

Keyword metrics are a **snapshot, not a live reading**. `power catamaran` at KD 28 today can be KD 32 next
quarter, which would place a published article on the wrong side of the threshold retroactively. So every
keyword stores `measured_at` and the `database` it was measured against, and every UI surface shows the
measurement date beside the figure. The system never presents a cached number as though it were current.

`database` defaults to `us`. Volume differs substantially by region, so this is a real knob for
EU- and Caribbean-facing brokers, not a formality.

### Where the data comes from

The engine reads keywords from the `keyword` table. **How that table is filled is pluggable**, which
matters because of a constraint worth stating plainly: the Semrush connection available today is an **MCP
server bound to an interactive Claude session** — the headless `bce` pipeline cannot call it. Live
autonomous lookups would require Semrush's Standard API and its own key and entitlement, which is a
separate commercial question.

So the seam at `AngleClient(keyword_source=...)` is filled in two stages:

1. **Now — an operator-curated bank.** The operator does their own Semrush research and exports a CSV,
   which is imported into the `keyword` table (`bce keywords import`). This works today with no new
   entitlement, and it is *better* than an automated lookup rather than a fallback from one: which keywords
   are commercially worth chasing is a judgement about the business, not a metric. Keyword economics in a
   niche this narrow also move on a quarterly timescale, so a curated bank refreshed occasionally loses
   nothing to a live call, and costs nothing per draft.
2. **Later — live.** A `SemrushClient` implementing the same interface, if and when API access exists.

Nothing downstream knows which one it is talking to.

**The import is a real ingestion problem, not a file read.** Semrush emits different headers per tool,
comma *and* semicolon delimiters, Excel BOMs, thousands separators, and blank or `n/a` metrics. The
importer tolerates all of it, and any row it cannot parse is **skipped and reported, never guessed** —
silently dropping a keyword the operator deliberately chose is the worst available failure.

**The operator exports their whole considered list, not a pre-filtered one.** Everything parsable is
imported and `qualifies` is recorded per keyword; only qualifying keywords are eligible for automatic
selection. The import then reports the split — how many qualified, how many missed which threshold. That
report is the substance of the feature: it tells the operator what their research actually yielded, and
where the data disagrees with their instinct.

### When nothing qualifies

If no banked keyword clears both thresholds for an angle, the system **does not relax the thresholds and
does not invent a keyword**. The draft is still written, the keyword box says plainly that no qualifying
keyword was found, and the operator sees it at review. Silently lowering the bar would make the box a
decoration — the number is only worth showing if it is allowed to say no.

## 6. Volume ceiling

**Hard cap: 50 brokers. Default working set: 20.**

The 60ft+ multihull brokerage world is small and relationship-driven; outreach at scale burns relationships worth more than any placement. With the dealer segment gone there is no longer a warm audience to absorb volume, which makes this cap more important, not less. Raising it requires a deliberate, recorded decision by Luis.

## 7. Tech stack

Matching what is already on this machine:

**Pipeline**
- **Python 3.11.9**
- **trafilatura** — boilerplate-free article extraction
- **Playwright** — JS-rendered sites (many broker sites are SPA)
- **httpx** — fetching with per-domain rate limiting
- **SQLite** — single source of truth for state, behind a thin data-access layer
- **Anthropic API, Claude Opus 4.5+** — voice analysis and drafting
- **Embeddings + numpy** — corpus-wide uniqueness gate (§10.3). At the 50-draft cap this is cosine similarity over ~50 vectors; a vector database would be premature
- **pytest** — TDD per `superpowers:test-driven-development`

**Deferred dependencies — designed for, not built against**

| Dependency | Purpose | Status | Adoption trigger |
|---|---|---|---|
| **Supabase** (Postgres + pgvector) | Hosted store, multi-user access, vector search at scale | Evaluated, deferred | **A second human in the system** — the moment the review gate has a non-Luis owner or the creative team needs access, a local SQLite file stops working. Not volume; volume is fine in SQLite |
| **Dropbox asset library** | Marketing-approved images/video via API | Creative team building; 1–2 weeks | Ships when the API exists. Consumed through `AssetProvider` (below) |
| **Semrush MCP** | Discovery recall, competitive context | Awaiting org owner approval | Improves Stage 1; never a dependency |

`AssetProvider` interface, so Stage 4b is a drop-in when Dropbox lands:

```
class AssetProvider(Protocol):
    def find_assets(self, theme: str, count: int) -> list[Asset]: ...

class NullAssetProvider:   # v1 — drafts ship text-only
    def find_assets(self, theme, count): return []
```

**Operator UI (§9)**
- **FastAPI** — imports the pipeline directly; no API boundary to maintain
- **HTMX** — partial page swaps via a script tag; no npm, no bundler, no build step
- **Jinja2** templates, plain CSS
- **uvicorn** — `localhost:8000`

Rationale: one language end to end, and no frontend toolchain to break. Streamlit was considered and rejected — faster to a first screen, but it fights editable queues and per-row actions, which is the entire app. Tauri is deferred; it can wrap the same local server later if a native feel is wanted.

## 8. Data model

```
broker(id, name, domain, region, segment_evidence, source,
       sunreef_affinity, affinity_evidence, has_editorial, has_newsletter,
       newsletter_evidence, qualified, qualified_reason,
       robots_allowed, created_at)

voice_profile(broker_id, register, avg_sentence_len, typical_word_count,
              structure_pattern, vocabulary_markers[], themes[],
              audience_signal, sample_quotes[], analyzed_at)

angle(id, broker_id, title, premise, audience_value, sunreef_relevance,
      score, rejected_reason)

keyword(id, phrase, volume, difficulty, intent, database, measured_at,
        qualifies, source)

draft_keyword(draft_id, keyword_id, role)

draft(id, angle_id, format, body_md, word_count, sunreef_mentions,
      passes_editorial_value_test, passes_uniqueness, max_similarity,
      most_similar_draft_id, passes_originality, embedding,
      status, reviewed_by, reviewed_at, reviewer_edits)

draft_asset(draft_id, asset_id, provider, usage_rights_confirmed)

outcome(draft_id, sent_at, response, published_url, utm_campaign,
        referral_sessions, inquiries)
```

`broker.source` ∈ `discovered | manual`.
`broker.sunreef_affinity` ∈ `none | mentions | lists_inventory | unknown` — ordering only (§4).
`broker.has_editorial` and `broker.has_newsletter` are independent booleans; qualification requires at least one (§4).
`draft.format` ∈ `long | medium | short` — see §5 Stage 4. Uniqueness comparison is scoped **within format**, so three buckets: a pillar piece is never compared against a newsletter blurb, and an article never flags as a duplicate of its own summary.
`draft.status` ∈ `pending_review | approved | rejected | sent | published | declined`.
Nothing reaches `sent` without a human in `reviewed_by`.
`keyword.qualifies` is **stored, not computed at read time** — it records whether the keyword met the §5b thresholds *at `measured_at`*, so a draft can always explain why a keyword was chosen even after the metrics drift.
`draft_keyword.role` ∈ `primary | secondary`. Exactly one `primary` per draft.

## 9. Operator UI

A review surface nobody can operate is a surface nobody uses. This is not optional polish: since 2026-09-02 the UI's job is **sampling** (§10.9) rather than per-draft approval, and a sample nobody reads is how gate drift goes unnoticed. It still needs the best interface in the system.

**Run:** `uvicorn app:app --reload` → `http://localhost:8000`. Single process, reads and writes the same SQLite file as the pipeline.

**Screens:**

| Screen | Purpose |
|---|---|
| **Dashboard** | Counts by stage, drafts awaiting review, recent outcomes |
| **Shortlist** | List/filter brokers by status and affinity. Add manually. Approve/reject discovered candidates |
| **Broker detail** | Voice profile rendered readably — register, themes, sample quotes, audience signal, affinity evidence |
| **Review queue** | *The core screen.* Draft beside its voice profile and angle rationale. Inline edit. Approve / reject / request-new-angle. Records reviewer identity and edits. Ordered by affinity |
| **Outreach** | Approved drafts with copy-ready message. Mark as sent |
| **Outcomes** | Published URLs, UTM campaign, referral sessions, inquiries |

**Keyword panel.** Every draft shown to the operator carries a keyword box: the primary and secondary
keywords baked in, each with its difficulty, average monthly volume, and measurement date (§5b). The
operator sees this at review so a weak keyword can be caught *before* the draft reaches a broker. The same
component renders in the broker portal (§9b) against the same data — it is written once, and the broker
sees exactly what we saw.

**Constraints:**
- Localhost only, no auth in v1 — single operator on one machine. Auth is required before this is exposed to anyone else.
- No destructive actions without confirmation. Rejecting a draft archives it; nothing is hard-deleted.
- Every state change writes `reviewed_by` and a timestamp. The audit trail is the point.

## 9b. Broker-facing portal (committed, not yet designed)

Decided 2026-09-01. **Everything in §9 is the admin side — ours.** A second surface follows: a portal
where each broker signs in and collects the content produced for them, refreshed weekly.

This is a different system from §9, not an extension of it, and the differences are the hard part:

| §9 admin UI (built) | §9b broker portal (not built) |
|---|---|
| Localhost, no auth | Public host, real authentication |
| One operator, sees everything | Multi-tenant — **broker A must never see broker B's content** |
| SQLite file | Hosted database |
| No secrets | Password hashing, sessions, reset flows |
| Read-only reviewing | Broker-facing delivery |

**This fires the Supabase adoption trigger** recorded in §7 — "a second human in the system." Row-level
security is the reason: the worst failure this system can have is one broker seeing another's drafts,
and that is a database-level guarantee, not something to hand-roll in application code.

**Consequences that land before the portal is built:**

- **§7's `AssetProvider` stops being optional.** A portal implies each broker collects a recommended
  image alongside the copy. That is the Dropbox library the creative team is building.
- **§10.7 usage rights become an exposure, not a note.** Self-serve download by a third party is a
  different act from a human emailing an image with context. Settle the rights language with creative
  before any asset reaches the portal.
- **Weekly cadence implies scheduling** — something must decide what each broker gets each week, and
  the §11.5 spend ceiling was written for manual operator runs, not a recurring job.
- **Nothing built so far is wasted.** The engine, the shortlist, the profiles and the admin UI all
  stand. The portal reads the same data through a different door.

The split above is recorded so it is deliberate rather than discovered late. What the broker actually
*initiates* is settled below; the rest — schema, hosting, session handling — is still not designed here.

### What the broker initiates — resolved 2026-09-02

The operator described the portal as: the broker signs in, **clicks to have the engine generate content
options**, and reviews them. That is a different system from the paragraph above, where content is
produced and reviewed by Sunreef and the broker collects it. The difference is not cosmetic — it changes
who sees model output first.

**Resolved: a broker initiates *angle selection*, never *generation*.**

> **The rule.** A broker may trigger work. What they trigger lands in the Stage 5 review queue,
> never in their hands.

**What forced it — Stage 5 (§5).** *"Nothing proceeds without explicit approval. Cannot be automated or
bypassed."* A Generate button that shows its output to the broker drives straight through the one gate
this spec protects hardest, and it does so on the default path, not in a corner case. The risk behind
that gate is the only one §12 rates **Critical**: fabricated Sunreef specifications published
externally. §10.4 now forbids any specific claim about a named Sunreef vessel outright — mechanically, in `bce.claims` — rather than requiring each be verified against official material, which is the form that rule took when this paragraph was written, and
Stage 5 is the only thing standing between the model and a broker's blog.

**The flow:**

1. Weekly, the engine proposes each broker's slate — 3–5 angles, one call capped at
   `MAX_TOKENS = 2048` — and the operator approves it in the admin UI
2. **A human at Sunreef messages the broker**: a friendly reminder that new angles are waiting.
   Consistent with Stage 6 (§5) — *"the system does not send email"* — this stays a person's job
3. The broker signs in and reads the slate. **It is fixed for the week**: the only set they choose
   from until the next cycle, with no reroll
4. The broker picks the one they like most — this is where their agency lives
5. The pick generates all **three formats** (long, medium, short) from that single angle
6. Each runs the §10.9 gate ensemble; anything that clears it is delivered, and a sample lands in the operator's queue for drift-checking (§10.9)
7. Once approved, the content appears in that broker's portal with its paired asset

**The weekly human message is what makes this safe as well as sociable.** Because a person is already
in the loop every cycle to send the reminder, approving the slate first costs nothing extra — so no
model output ever reaches a broker unreviewed, and the broker never waits on generation. There is no
"generate" button in this design: there is an approved slate and a nudge to come look at it.

**The fixed weekly slate is doing real work,** not just rationing. It bounds spend to one angle call per
broker per week against §6's 50-broker ceiling; it keeps the §10.3 uniqueness corpus single-writer,
since angle generation never touches it and only operator-approved drafts do; and scarcity makes the
choice considered rather than a slot-machine pull, which is the same reason §11 expects a partner who
chose the topic to actually publish it.

**Why this is the better system, not merely the safer one.** §11's own note is that a partner who chose
the topic is far likelier to publish it. Choosing the angle *is* that ownership — choosing among finished
articles is not, because by then the editorial decision has already been made for them.

**Three consequences that follow, all of which a Generate button would have broken:**

- **Spend stays bounded and attributable.** `MAX_DRAFT_CALLS = 7`, `MAX_PROFILE_CALLS = 20` and §6's
  50-broker ceiling were all written assuming the operator initiates, and §6 requires that raising the
  ceiling be *"a deliberate, recorded decision by Luis."* A Generate button delegates volume to 20–50
  external users at Opus pricing; a broker who dislikes an output and clicks again four times has made a
  spending decision nobody recorded. One draft per deliberate angle choice keeps §11.5's ceiling
  meaningful.
- **The uniqueness gate stays single-writer.** §10.3 compares each draft against every draft ever
  produced and regenerates on rejection, with rejected drafts still counting as seen. Concurrent
  broker-triggered generation makes that a race: two brokers drafting near-identical angles at once,
  first commit winning, the corpus mutating under both. Queued selection serialises it.
- **Latency stops mattering.** Angle proposal plus a 2,000–2,300 word pillar plus an embedding
  round-trip is minutes, not a request/response. Asynchronous by construction, a pick today collected
  tomorrow also *reads* as considered rather than machine-generated.

**Field-level visibility — the broker sees a subset of an angle.** The `angle` row carries five fields
(§8). Three are shown, two are not:

| Field | Shown to broker | Why |
|---|---|---|
| `title` | Yes | It is the pitch |
| `premise` | Yes | What the article would argue |
| `audience_value` | Yes | Why *their* readers would want it — the argument for choosing it |
| `sunreef_relevance` | **No** | Literally "how this connects to catamaran ownership *without reading as an advertisement*". A broker reading that sentence sees the machinery behind their own editorial calendar |
| `score` | **No** | A numeric publishability rank on content pitched to them as tailored |

This split does not exist in the schema; it is a portal-template concern. Recorded now because it is
trivial before that template is written and awkward afterwards.

**Credential delivery.** The first email carries sample content as an attachment — it earns the click
before anyone is asked to sign in — and an **invite link with a single-use token**, never a username and
password. The broker sets their own password on first use. Emailed passwords persist in inboxes, get
forwarded, and mean Sunreef once knew the plaintext; for a partner-facing system carrying the Sunreef
name that is the wrong first impression. Supabase Auth provides invite and magic-link flows directly.

**Resolved — a human sees the slate first.** The concern was that requesting options would put model
output in front of an external partner with no Sunreef review: a narrower exposure than a
generate-a-draft button, since every draft still clears the §10.9 ensemble, but the same category. The constraints
on angle text — no fabricated vessel claims (§10.4), never naming a competitor — live only in the
`_SYSTEM` prompt, and this codebase is explicit that a prompt is a request rather than an enforcement:
*"the model's output is untrusted, and a `maxLength` in a JSON schema is not a guarantee."* The weekly
outreach settles it at no cost, per step 1 above.

**Cost of one cycle, for §11.5's ceiling.** A pick spends four calls — angles, long, medium, short
(`bce.cli`) — which at Opus pricing is on the order of **$0.15 per broker per cycle**. A full
50-broker week is therefore under $10 before uniqueness-rejection retries. §11.5 notes the budget has
no ceiling stated and that retries must be allowed for; these are the numbers to set it against, and
they make a recurring weekly job affordable in a way §9b's earlier note feared it might not be.

**OPEN — review granularity.** One pick yields three drafts, and §5 says the short form is *"a
condensation of the long form, not a separate piece: same angle, same claims, same voice."* So does
Stage 5 approve the package or each format independently? Approving a package is fewer decisions and
matches how the three are actually produced; approving individually lets a reviewer keep the long form
and reject a weak condensation, which `bce.cli`'s own reporting already distinguishes ("long draft
kept, medium and/or short condensation..."). Decide before the review queue is built for the portal.

### Portal telemetry — what the broker actually uses

Decided 2026-09-02. Sunreef needs to know which option each broker takes. Four mechanisms, weakest
first; the fourth is the one that closes the loop.

1. **Copy button, logged.** Records `(broker_id, draft_id, format, timestamp)` before writing to the
   clipboard. Reliable for the button, and **only** for the button — intercepting a mouse selection and
   ⌘C is unreliable and reads as surveillance. The answer is design, not code: make the Copy button the
   *convenient* path — one click, formatted, ready to paste — so nobody bothers selecting by hand.
2. **Download button, logged.** The same record. The natural path once a paired asset is involved.
3. **UTM links** (§5, Stage 7). Already designed, and the strongest *outcome* signal, because it counts
   readers rather than intent.
4. **Publication detection, reusing the fingerprint machinery.** Broker articles are already shingled
   into `source_fingerprint` for §10.3's originality gate, and Stage 2 already crawls broker editorial
   sections. Point the same containment measure the other way: re-crawl periodically, shingle new
   articles, and test them against drafts delivered to that broker. This detects publication **even
   when nobody clicked anything, and even when the broker edited the piece** — which they will, and
   should. No click-tracking can answer "what did they actually run"; this can.

New table, feeding the same funnel view as `outcome`:

```
portal_event(broker_id, draft_id, format, event, occurred_at)
   event IN ('viewed', 'copied', 'downloaded')
```

**Tell the brokers.** One line in the portal — *we track which pieces get used so we can send you
better ones*. Several are EU-based, this is a partner surface carrying the Sunreef name, and silent
behavioural logging is both a trust problem and a GDPR question worth not having. Said plainly it reads
as a feature.

**Still not designed here:** the queue and worker that turn a pick into a draft run, portal schema and
row-level security policies, hosting, session handling, and how the weekly cadence in the paragraph above
interacts with picks a broker has already made.

## 10. Compliance and ethics constraints

Requirements, not preferences:

1. **Disclosure — BLOCKING.** Ghostwritten content published under a broker's byline promoting Sunreef may trigger advertising-disclosure obligations (EU UCPD; Polish consumer law; FTC endorsement guides for US-facing content). With the dealer segment gone, every placement is now this case. **Legal review is required before the first outreach, not before scaling.** Default position: offer brokers clear attribution language ("in partnership with Sunreef").
2. **Crawling.** `robots.txt` respected. Rate limit ≥2s per domain. Identifying User-Agent with a contact URL. No login-gated or paywalled content.
3. **Originality — three distinct checks.** "Unique, tailored, original" are three different guarantees requiring three different mechanisms. All three are blocking gates before a draft reaches review:

   | Check | Compared against | Mechanism | Fail action |
   |---|---|---|---|
   | **Unique** | Every other draft ever produced | Embedding cosine similarity across the draft corpus; threshold 0.88 | Reject, regenerate from a different angle |
   | **Tailored** | This broker's voice profile | Register/structure match scored in Stage 4 | Reject, redraft |
   | **Original** | The broker's own published prose | Near-duplication check against the source corpus | Reject, redraft |

   Voice profiles store derived features and short quotes, never full article text. Every draft's embedding is persisted so the uniqueness corpus grows monotonically — a draft rejected for similarity still counts as seen, so the system cannot oscillate between two near-identical angles.

   **Resolved 2026-09-02 — how *Original* compares against prose we deliberately do not keep.** As written, the two paragraphs above contradicted each other: the *Original* gate compares a draft against "the broker's own published prose", while the privacy rule forbids storing that prose. Broker articles are fetched during profiling (`articles.collect_broker_articles`) and discarded, so the gate had nothing to run against and was never implemented.

   The gate stores **shingle fingerprints, not prose**: overlapping 6-word n-grams from the broker's fetched articles, hashed, in a `source_fingerprint(broker_id, shingle_hash)` table. Near-duplication is then a containment measure between the draft's shingle set and the broker's. No recoverable text is stored, so the privacy constraint holds literally rather than by interpretation, and the gate becomes real.

   Containment threshold: **0.5**. This is a first estimate and needs calibration against real drafts — it has only ever run against synthetic bodies, so treat the number as provisional until the first live run.

   **Unverifiable is not the same as clean.** If the embedding call fails — no API key, network error, refusal — the uniqueness gate returns *fail*, not pass. A blocking gate that silently degrades to "fine" when it cannot check is worse than no gate, because it reports confidence it never earned. The practical consequence is that **without `VOYAGE_API_KEY` configured, every draft is rejected**, which is intended and loud rather than silent.

   **`tailored_score` distinguishes zero from not-comparable.** A profile carrying a register but no statistics is a legitimate state — drafting refuses only when `register` is NULL. For such a broker the tailored score is `NULL` ("nothing to compare"), never `0.0`, and it does not block. A fabricated zero would be indistinguishable from a genuinely terrible voice match and would reject every medium and short draft for any thinly-profiled broker.

7. **Asset usage rights.** Marketing-approved-for-Sunreef is not the same as licensed-for-a-third-party-to-republish. Any image or video supplied to a broker must carry explicit permission for that broker to publish it on their own site. **Resolve with the creative team while the asset library is being built (§11.3), not after.**
4. **Factual accuracy — BLOCKING, and enforced by refusal rather than verification.** Fabricated specifications reaching a broker's blog remains the highest-severity failure mode in this system. **Revised 2026-09-02:** rather than requiring each claim be *verified* against official Sunreef material — which needs a source of truth that does not exist, and which neither a reviewer nor a judge model can substitute for — drafts may make **no specific factual claim about any named Sunreef vessel at all**: no dimension, no capacity, no performance figure, no certification. This costs nothing editorially, because §5b's intent rule and `_SYSTEM`'s "not an advertisement for any yacht brand" already push every angle toward category content rather than product content. A gate that blocks a claim is mechanical and testable; a gate that verifies one is a research project. See §10.9.
5. **Honest attribution in outreach.** Messages state plainly that Sunreef prepared the draft.
6. **Relationship-agnostic copy.** Because affinity detection is incomplete (§4), no outreach may assume the recipient is a stranger to Sunreef.

### 10.8 Decisions on the IT risk assessment (2026-09-02)

Sunreef IT produced a preliminary risk assessment of this project. Its technical findings were
remediated in code (SSRF, operator-panel authentication, CSRF, upload ceiling, throttling,
prompt-injection fencing). The items below are **decisions rather than defects** — recorded here so
they are deliberate and reviewable, not gaps someone later mistakes for oversights.

**Repository visibility — decided, and the window is still open.** The repository is private by
default; it was made public so the IT reviewer could read it, and returns to private once the build is
complete. **As of this writing it is still public**, which the licence review below makes a compliance
matter as well as a security one.

Measured rather than assumed: 0 forks, 0 stars, 0 watchers and 0 clones across GitHub's 14-day traffic
window. That is what makes a git-history rewrite the wrong remedy — with no fork network preserving
commits, the content goes private when the repository does. What the traffic API does not count is
web-UI browsing, `raw.githubusercontent.com` fetches, or the public events firehose, which archives
repository names, SHAs and **commit messages** though not file contents. So the honest read is "very
low, and not worth a history rewrite", not "provably zero" — and "we made it private again" is still
not the same as "it was never public".

**Semrush data — reviewed 2026-09-02. The IT finding's word "redistribution" does not fit the private
case.** ToS §3.2 grants use "solely for your own internal business purposes", which is what choosing
article topics is; §3.3(a) bars making the Services available to a *third party*, and a private company
repository contains none. No general storage or retention limit exists — the one-month cache cap in
§3.3 is expressly conditional on *"If you subscribe to the Semrush API"*. **Resolved 2026-09-02: the export came from the
web UI, not the API**, so the cap does not attach. There is no retention deadline on this data, nothing
to ask Semrush for, and no recurring exposure — the file can stay as long as it is useful. Had it been
an API export, the cap would have bitten around 2026-10-01 for a file measured 2026-09-01 and turned a
one-off into a standing breach; worth knowing if anyone ever wires up a live API pull, because that
export would carry the cap.

The public window is a probable technical breach of §3.3(m) while it lasts, cured by going private,
with a 30-day cure right under §7 and no liquidated damages. Two structural notes for anyone
revisiting this: Sunreef is Polish, so §11.4 makes this an **Irish-law** contract rather than a US one,
and the EU **sui generis database right** (Directive 96/9/EC; Polish Act of 27 July 2001) applies
independently of contract and is not displaced by that clause. Both point to the same remedy, so
neither changes what to do.

**Acted on.** `CPC (USD)` and `SERP Features` were stripped from the raw export: they are Semrush's own
commercial analysis, the highest-sensitivity fields in any export, and **no code here has ever read
them** — pure exposure for zero utility. Every tracked Semrush file now carries a provenance and
licence-basis header, and `tests/test_repo_hygiene.py` asserts both the absent columns and the present
header, because `load_bank` silently drops unmapped columns and a re-added CPC column would otherwise
be noticed by nobody.

**The forward risk is §3.3(r)**, which forbids Semrush outputs as inputs to a language model. The code
is compliant today by design — only `phrase` reaches a prompt, never a figure — but
`angles.AngleClient.keyword_source` is an unwired seam that would fold live Semrush results into one.
The rule is written at that seam and asserted by a test: phrases may enter prompts, figures may not.

**Transfer of broker content to Anthropic and Voyage — accepted, no separate legal review.** The
assessment recommended a legal/privacy review before broker article text is sent to external AI
providers. Luis's decision is to proceed without one. The facts that make that defensible, and which
should be given alongside the decision rather than left implied: the material is **public web
content**, retrieved from pages any reader can open, never login-gated or paywalled (§10.2). Voice
profiles store **derived features and short illustrative quotes, never full article text** (§5 Stage
3). §10.3's originality corpus stores **shingle hashes, not prose** — there is no recoverable text in
the database at all. So what leaves Sunreef is a bounded excerpt of already-public writing, sent for
style analysis. This is not a decision to send confidential third-party material anywhere, and stating
it that way is more accurate than the assessment's framing.

**Identifying the crawler as Sunreef before a partnership exists — resolved, and the concern does not
apply.** The assessment suggested `SunreefPartnerContentBot` should perhaps not name Sunreef to a
broker who has not yet agreed to work with us. **There is no such state.** Sunreef holds no ongoing
agreements with brokers. A broker signs a single-deal sales agreement only when they bring an active
referral, so "before a partnership exists" describes every broker, permanently — including the ones
already selling boats for us. The whole purpose of this programme is to help brokers manufacture
opportunities that lead to exactly those single-deal agreements. An identifying User-Agent is
therefore correct, and remains what §10.2 requires: a bot that named itself something opaque while
crawling on Sunreef's behalf would be the worse choice, both ethically and reputationally.

**Broker consent before voice profiling — decided: not sought.** Profiling is automation in service of
the broker, not surveillance of them: its only purpose is that when a broker opens the portal, the
content waiting for them already matches their brand, voice and tone rather than reading like generic
manufacturer copy. Asking permission to read pages that are already public, in order to write
something better for the person who published them, inverts the relationship the programme is trying
to build.

One factual note attaches to this decision, recorded so the answer exists if it is ever asked for. A
brokerage is a business, and business data is not personal data. But a broker's articles may carry a
named author, and analysing an identified person's writing style can touch personal data under GDPR.
The design already limits that exposure structurally rather than by policy: only public pages, derived
features and short quotes rather than stored prose, hashes rather than text in the originality corpus,
and no special-category data of any kind. Combined with §10.1's disclosure work and §10.5's honest
attribution, the position is a defensible legitimate-interest one. If a broker ever objects, the
answer is to delete their profile and stop — which the data model supports today, since everything
about a broker hangs off one row.

### 10.9 The gate ensemble, and what replaced the human approval

**A §10 edit is not finished until the circulated material matches it.** This section's first
revision left three already-distributed documents — `docs/leadership-brief.html`,
`docs/content-engine-brief.md` and the broker-facing `docs/broker-channel-onepager.html` — promising
that "a human still approves every single piece", four hours after that control was removed. An
independent evaluation on 2026-09-02 found it. Telling leadership about a control that no longer
exists forfeits the credit earned by every conservative decision in this repository; telling a
*broker* is worse, because it is the assurance they would rely on. The decks are versioned with this
document.

Revised 2026-09-02. **Stage 5's blocking human approval is removed.** A draft ships when it clears the
ensemble below; the operator reads a sample afterwards rather than approving each item.

**Why this holds.** The broker is the human in the loop, and for editorial judgment a better one than a
Sunreef reviewer: it is their masthead, their readers, their voice, and nothing reaches the public
without them choosing to publish it. A draft they dislike is simply not used, which is a real filter
with real stakes on it.

**Where the broker is structurally blind, and the one thing that had to change with it.** A broker
cannot assess a claim about a Sunreef vessel. They are not the manufacturer; a fabricated dimension or
certification looks authoritative, concerns *our* product, and they would publish it in good faith —
the §12 Critical risk, arriving by the one route their judgment cannot cover. **A judge model does not
fix this either.** Checking one model's claims about Sunreef vessels with another model is two guesses,
not a verification, and where both share a lineage their blind spots are *correlated* with the
author's. This spec is already explicit that the model's output is untrusted and that a schema
constraint is a request rather than a guarantee; the same applies to a judge's prompt. So §10.4 was
rewritten to **refuse product claims rather than verify them** — mechanical, testable, and free,
because category content never needed them.

**The ensemble.** Six gates. The first three exist; the last three are new.

| Gate | Compared against | Mechanism | Kind |
|---|---|---|---|
| **Unique** (§10.3) | Every draft ever produced | Embedding cosine, threshold 0.88 | Mechanical |
| **Tailored** (§10.3) | This broker's voice profile | Register/structure score | Mechanical |
| **Original** (§10.3) | The broker's own prose | Shingle containment, threshold 0.5 | Mechanical |
| **No product claims** (§10.4) | Named Sunreef models | Refuses any specific figure or certification attached to a Sunreef vessel — `bce.claims`, blocking for every format | Mechanical, **built** |
| **Editorial value** (§3) | The broker's own blog | Judge: *strip every Sunreef mention — is this still worth publishing here?* | Judge, not built |
| **Brand quality** | Sunreef's standards | Judge: does this represent the brand at the quality we would sign? | Judge, not built |

**Every gate fails closed.** §10.3 already sets the rule — *unverifiable is not the same as clean* —
and it now governs all six. A judge call that errors, times out, or refuses is a **reject**, never a
pass. A gate that silently degrades to "fine" when it cannot check is worse than no gate, because it
reports confidence it never earned.

**Judge independence is a requirement, not a preference.** The two judge gates must not run on the same
model instance and prompt lineage that wrote the draft. Prefer a different model; prefer mechanical
checks wherever a rule can be expressed as one. A judge that shares the author's blind spots is
theatre.

**Sampling replaces gating, on a schedule — and the order matters.** Nothing in this pipeline has ever
run against a real broker, and two of the three existing thresholds are explicitly first estimates
awaiting calibration. Removing human review *before* the gates have been observed working once would
be calibrating away a control that has never been measured. So:

| Phase | Operator sample |
|---|---|
| First pilot run | **100%** — every draft read, as today, but as observation rather than approval |
| Once the gates have held across a full run and the two thresholds are calibrated | Step down deliberately, recorded, and never to zero |
| Steady state | A floor high enough to notice drift; agents degrade quietly, and without a sample the first report comes from a broker |

**Unaffected.** §10.1's legal review is a disclosure obligation, not a quality gate, and remains
**blocking before first outreach**. §10.2 crawling, §10.5 attribution, §10.6 relationship-agnostic copy
and §10.7 asset rights all stand unchanged.

## 11. OPEN DECISIONS

**Resolved since v0.2:**
- ~~Dealer list sourcing~~ → Not available (IT). Segmentation removed; affinity signal substitutes for ordering only (§4).

**Still open:**

1. **Sampling ownership.** Who at Sunreef reads the Stage 5 sample? **Downgraded from blocker 2026-09-02 (§10.9):** with the gate ensemble shipping drafts on its own, an absent owner no longer stalls the pipeline — which is exactly why this now needs naming rather than assuming. Unread samples are how gate drift reaches a broker before it reaches us, and §10.9 sets the first pilot run at 100%. Someone needs the time and the machine.
2. **Legal review.** §10.1 is now blocking before first outreach. Who initiates it, and on what timeline? Build can proceed in parallel; sending cannot.
3. **Asset library.** Creative team is building a Dropbox of marketing-approved images/video with API access, 1–2 weeks out. Two things needed from them: the API shape, and **written confirmation that brokers may republish the assets** (§10.7). Build proceeds against `NullAssetProvider` meanwhile.
4. **Languages.** Sunreef sells into non-English markets. *Assumed: English-only for v1.*
5. **Claude API budget.** No ceiling stated. *Assumed: needs a cap before any looped execution.* Note the uniqueness gate (§10.3) causes rejected drafts to be regenerated, so budget must allow for retries, not just one draft per broker.
6. **v1 success definition.** **Revised 2026-09-02.** Was *"3 brokers publish, and referral traffic is measurable in GA4 within 90 days"* — unachievable as written, because referral traffic requires a link and §1 closed that question (see Stage 7). Now: **3 brokers publish at least one delivered piece within 90 days, detected by fingerprint match (§9b), and at least 2 of them return for a second angle.** Publication is the outcome; the return is what says it was worth their time rather than merely tolerable. Still needs agreement — this is the number the project gets judged on, and it is now a number the project can actually produce.

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Fabricated Sunreef specs published externally | **Critical** | §10.4 no-product-claims gate — `bce.claims`, mechanical, blocking for every format, with its own evasion path recorded as a passing test; plus 100% operator sampling for the first pilot run (§10.9). **The former mitigations named here — a §10.4 verification gate and Stage 5 human review — no longer exist** (revised 2026-09-02) |
| Undisclosed advertising exposure | **High — now universal** | §10.1 legal review, blocking before first send |
| Zero broker uptake | High | Affinity-ordered queue; §13's manual pilot before code — **not yet run**. The editorial value test (§3) is now a §10.9 judge gate and is **not built**, so this risk is presently mitigated by sequencing alone |
| Perceived as spam; relationships damaged | High | §6 cap; human-sent, personalized, relationship-agnostic copy |
| Cold pitch lands on an unrecognized existing partner | Medium | §10.6 relationship-agnostic copy; affinity signal catches the detectable cases |
| No review owner → pipeline stalls | High | §11.1 — resolve before build completes |
| Broker sites block crawler | Medium | Respect robots.txt; degrade to manual profiling |
| Drafts converge — 30 near-identical catamaran articles | **High** | §10.3 uniqueness gate; embeddings persisted so rejected drafts still count as seen |
| Assets republished without broker usage rights | High | §10.7 — settle rights with creative team before first asset ships |
| Voice mimicry reads as inauthentic | Medium | Tailored gate (§10.3, blocking for medium/short); operator sampling (§10.9); brokers edit freely |

## 13. Suggested first milestone

Per the playbook's "start with one, then scale": **run the full pipeline manually for exactly one broker, by hand, before writing code.** Profile their voice, write one article, pitch it.

This matters more in v0.3 than it did in v0.2. The dealer path would have given a near-certain first yes; without it, "will an independent broker publish this?" is a genuine open question and the central risk of the project. Answer it for one broker, by hand, in a day.

Choose a **high-affinity** broker for the pilot — one whose site already lists Sunreef inventory. Not to give them special treatment, but because a pilot should test the editorial engine, not the hardest possible sales conversation at the same time.

Pass condition: one broker publishes, or says they would. Fail condition: three brokers decline — at which point the premise needs rethinking, not more automation.

---

## Spec self-review

Per `superpowers:brainstorming` §Spec Self-Review.

- **Placeholders:** none — open items enumerated in §11 rather than hidden as TBDs.
- **Contradictions:** §2 forbids tiered service while §4 orders the queue by affinity; resolved explicitly in §4 — ordering is not differential treatment, and the ✅/❌ list states exactly what the signal may and may not touch. §1 rejects backlinks as the metric while §7 retains Semrush; resolved — Semrush serves discovery and competitive context, not link measurement.
- **Ambiguity:** "Sunreef's segment" defined concretely in §4. Affinity is a stored enum with defined values, not a runtime judgment.
- **Type consistency:** v0.2's `partner` table reverted to `broker`; `segment` field removed; `sunreef_affinity` and `affinity_evidence` added. All references updated (§5, §8, §9).
- **Scope:** two subsystems — pipeline and UI — sharing one SQLite store and one repo. The UI is not independently useful, so a single plan still holds. If the plan exceeds roughly 15 tasks, split at that point.
- **Known weakness:** affinity detection is heuristic and will have false negatives — a broker with a real Sunreef relationship that is not visible on their public site reads as `none`. §10.6 (relationship-agnostic copy) is the mitigation, and it is a requirement rather than a nicety precisely because the signal cannot be trusted to be complete.
