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

Every draft must pass the **editorial value test**: *if every Sunreef mention were removed, would this still be worth publishing on this broker's blog?* If no, the draft is rejected. This is a hard gate (§5, Stage 5), not a guideline, and it now applies to every draft without exception.

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

Seven stages. Stages 1–4 automated; **Stage 5 is a human gate operated through the UI (§9)**; 6–7 human-led with tooling support.

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

**Stage 5 — Human review gate.** Operated in the UI. Reviewer sees the voice profile, the angle rationale, and the draft; edits inline; approves or rejects against the editorial value test. Nothing proceeds without explicit approval. Cannot be automated or bypassed.

**Stage 6 — Outreach.** Produces a personalized, relationship-agnostic message plus the draft, for a human to send. The system does not send email.

**Stage 7 — Measure.** UTM-tagged links, referral traffic by broker, engagement, inquiries attributed to broker referral.

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

A review gate with no surface to operate it is a gate nobody walks through. This is not optional polish — Stage 5 is the step that cannot be automated, so it needs the best interface in the system.

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

Not designed here. Recorded so the admin/broker split is deliberate rather than discovered late.

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

7. **Asset usage rights.** Marketing-approved-for-Sunreef is not the same as licensed-for-a-third-party-to-republish. Any image or video supplied to a broker must carry explicit permission for that broker to publish it on their own site. **Resolve with the creative team while the asset library is being built (§11.3), not after.**
4. **Factual accuracy.** Any claim about Sunreef vessels — dimensions, specs, certifications — must be verifiable against official Sunreef material. Fabricated specifications reaching a broker's blog is the highest-severity failure mode in this system.
5. **Honest attribution in outreach.** Messages state plainly that Sunreef prepared the draft.
6. **Relationship-agnostic copy.** Because affinity detection is incomplete (§4), no outreach may assume the recipient is a stranger to Sunreef.

## 11. OPEN DECISIONS

**Resolved since v0.2:**
- ~~Dealer list sourcing~~ → Not available (IT). Segmentation removed; affinity signal substitutes for ordering only (§4).

**Still open:**

1. **Review ownership.** Who at Sunreef operates the Stage 5 queue? The UI makes this concrete — someone needs the time and the machine. Without a named owner the pipeline stalls at its most important step. **This is the single unresolved blocker.**
2. **Legal review.** §10.1 is now blocking before first outreach. Who initiates it, and on what timeline? Build can proceed in parallel; sending cannot.
3. **Asset library.** Creative team is building a Dropbox of marketing-approved images/video with API access, 1–2 weeks out. Two things needed from them: the API shape, and **written confirmation that brokers may republish the assets** (§10.7). Build proceeds against `NullAssetProvider` meanwhile.
4. **Languages.** Sunreef sells into non-English markets. *Assumed: English-only for v1.*
5. **Claude API budget.** No ceiling stated. *Assumed: needs a cap before any looped execution.* Note the uniqueness gate (§10.3) causes rejected drafts to be regenerated, so budget must allow for retries, not just one draft per broker.
6. **v1 success definition.** Proposed: **3 brokers publish, and referral traffic is measurable in GA4 within 90 days.** Needs agreement — this is the number the project gets judged on.

## 12. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Fabricated Sunreef specs published externally | **Critical** | §10.4 verification gate; human review |
| Undisclosed advertising exposure | **High — now universal** | §10.1 legal review, blocking before first send |
| Zero broker uptake | High | Editorial value test (§3); affinity-ordered queue; manual pilot (§13) before code |
| Perceived as spam; relationships damaged | High | §6 cap; human-sent, personalized, relationship-agnostic copy |
| Cold pitch lands on an unrecognized existing partner | Medium | §10.6 relationship-agnostic copy; affinity signal catches the detectable cases |
| No review owner → pipeline stalls | High | §11.1 — resolve before build completes |
| Broker sites block crawler | Medium | Respect robots.txt; degrade to manual profiling |
| Drafts converge — 30 near-identical catamaran articles | **High** | §10.3 uniqueness gate; embeddings persisted so rejected drafts still count as seen |
| Assets republished without broker usage rights | High | §10.7 — settle rights with creative team before first asset ships |
| Voice mimicry reads as inauthentic | Medium | Human review; brokers edit freely |

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
