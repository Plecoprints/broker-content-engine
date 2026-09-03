# Where this project stands

Last updated 2026-09-02, at the point of moving development from a laptop to the Mac Studio.

Read [`README.md`](README.md) for setup and
[`docs/superpowers/specs/2026-08-20-broker-partner-content-design.md`](docs/superpowers/specs/2026-08-20-broker-partner-content-design.md)
for the binding design. This file is only the current state and the immediate next step.

## Built and tested

600 tests passing, no API keys or network required to run them.

| Stage | State |
|---|---|
| Broker shortlist import and qualification | Done |
| Voice profiling | Done |
| Keyword bank, five selection gates | Done — operator's approved/excluded banks are the authority (§5b) |
| Angle proposal and three-format drafting | Done |
| Originality gates (§10.3) + no-product-claims (§10.4) | Done — four of §10.9's six gates; the two judges are specified, not built |
| Operator UI (`bce serve`) | Done — shortlist, add brokers, draft viewer with keyword and gate panels |

## Never yet run against a real broker

This is the single most important thing to know. Every draft produced so far came from
eight invented example brokers on `.invalid` domains that cannot be crawled, written by
fake API clients. The pipeline has not touched a live website or spent a real API call.

Two numbers in particular are unvalidated and were chosen as first estimates:

- `originality.TAILORED_MIN_SCORE = 0.5` — the voice-match bar for medium/short drafts
- `originality.ORIGINALITY_MAX_CONTAINMENT = 0.5` — overlap with the broker's own prose

Both need calibration against real drafts. Expect to move them after the first pilot.

## Immediate next step: the pilot

Blocked on two inputs, both from the operator:

1. **API keys** — `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY` in the environment.
   Without the Voyage key **every draft is rejected**, by design (§10.3): the uniqueness
   gate is blocking and will not treat "could not check" as "fine".
2. **A real broker CSV** — two columns, `name,domain`, 20–30 rows for a first pilot.

Then run in this order, and **stop after `profile`**:

```bash
bce init
bce keywords data/keywords-approved.csv   # the only keyword source (§5b)
bce exclusions data/keywords-excluded.csv # blocklist; never selectable
bce import <brokers.csv>
bce qualify      # visits sites, respects robots.txt — cheap, reversible
bce profile      # learns each voice — cheap, reversible
# STOP. Read several voice profiles in the UI and check they describe brokers you
# recognise. If profiling is wrong, every draft built on it is wrong too.
bce draft        # spends real API budget; capped at 7 brokers per run
```

## Decisions that would otherwise surprise you

- **Stage 5 is no longer a blocking human approval** (§10.9, revised 2026-09-02). A draft ships
  when it clears a six-gate ensemble; the broker, who publishes or does not, is the human
  judgment on editorial fit; the operator reads a *sample* to catch gate drift. Three gates
  **Four are built** — unique, tailored, original, and the mechanical
  no-Sunreef-product-claims gate (`bce.claims`; §10.4 was rewritten to refuse claims rather
  than verify them, since verifying needs a source of truth that does not exist). The two
  judges, editorial-value and brand-quality, are specified but **not built**. Every gate fails closed, and the judges must not run on the model
  that wrote the draft. **Sampling starts at 100% for the first pilot run** and steps down
  only once the gates have been seen working — removing a control before it has ever been
  measured is not the same as trusting it.

- **The IT risk assessment is answered: six technical findings fixed, four items decided**
  (§10.8). Fixed in code — SSRF with two layers and per-redirect-hop validation, operator-panel
  authentication (a non-loopback bind is now *refused* without a password), CSRF, a 1 MB upload
  ceiling, write-path throttling, and prompt-injection fencing for scraped text. Decided, not
  defects — the repo is private by default and was public only for the review; transfer of
  public broker prose to Anthropic/Voyage is accepted without separate legal review; the
  identifying User-Agent stays, because Sunreef holds no ongoing broker agreements so "before a
  partnership" describes every broker permanently; and broker consent for profiling is not
  sought, since it exists to make portal content match their own voice.

- **Semrush data is cleared for private internal use** (§10.8). ToS §3.2 covers it; the finding's
  word "redistribution" does not fit a private repository. `CPC (USD)` and `SERP Features` were
  stripped from the raw export — Semrush's own commercial analysis, never read by any code here —
  and every tracked Semrush file states its provenance and licence basis, asserted by tests. The
  export came from the web UI, so §3.3's one-month cache cap does not apply and there is no
  retention deadline. **The standing rule is §3.3(r): keyword phrases may enter a prompt, Semrush
  figures may never.** Compliant today; the rule is written at `angles.AngleClient.keyword_source`
  because that unwired seam is where it would break.

- **There is no click attribution, by design, and that has a reporting consequence.** §1
  closed the backlink question — links are welcome if a broker offers one, but are not a goal
  and not designed for — because Sunreef supplies copy for a partner to paste into their own
  channels and never controls the published URL. Stage 7 and §11.6 were rewritten 2026-09-02
  to match: success is **3 brokers publishing a delivered piece within 90 days, detected by
  fingerprint match, and 2 of them returning for a second angle**. Never promise a
  referral-ROI figure for this channel — it cannot be produced. `outcome`'s `utm_campaign`,
  `referral_sessions` and `inquiries` columns are never populated; they are kept only in case
  that decision is reopened.

- **Long drafts are not blocked on voice match.** Voice matching is binding for medium and
  short, advisory for the 2,000–2,300 word pillar. No broker's typical article length is
  near 2,000 words, so a blocking check would fail every pillar.
- **`tailored_score` of `NULL` means "not comparable", not zero.** A broker profiled with a
  register but no writing statistics gets NULL and is not blocked.
- **The operator's two curated banks are the authority on keywords.**
  `data/keywords-approved.csv` (148) is the only source; `data/keywords-excluded.csv` (95) is a
  blocklist enforced as a fifth selection gate, in its own `excluded_keyword` table. It lives
  separately because the other four gates are derived from metrics and get recomputed by every
  import, while a human's exclusion has to survive them. Load both after `bce init`:
  `bce keywords data/keywords-approved.csv` then `bce exclusions data/keywords-excluded.csv`.
  `data/keyword_bank.sample.csv` is a test fixture, not a bank — never import it.

- **Keyword gates are four independent checks**, not one: difficulty, volume, segment
  relevance, and editorial intent. A keyword can pass the numbers and still be wrong —
  the operator's own export contained `catamaran stripe light blue-ivory area rug` at
  difficulty 6 with 260 monthly searches.
- **Competitor brands are gated, not excluded.** Lagoon, Leopard, Aquila et al. are
  imported and visible but never auto-selected. Opting one in is a human decision.
- **Segment relevance is heuristic** and will occasionally be wrong. The exclusion reason
  is stored per keyword so a bad rule can be spotted. There is no UI to correct it yet.

## Committed but not built

In order, all after the pilot:

1. **Broker-facing portal** (§9b) — partner logins, row-level security. **What the broker
   initiates is now settled (§9b, resolved 2026-09-02): angle *selection*, never
   generation.** Weekly: the engine proposes each broker's slate of 3–5 angles, the
   operator approves it, and **a human messages the broker** that new angles are waiting
   (Stage 6 — the system does not send email). The broker picks one; that pick generates
   all three formats, which run the §10.3 gates and land in the Stage 5 review queue, not
   in the broker's hands. The slate is fixed for the week — no reroll. Because a person is
   already in the loop each cycle to send the reminder, approving the slate first costs
   nothing, so no model output ever reaches a broker unreviewed. There is no "generate"
   button: there is an approved slate and a nudge to come look at it. A
   Generate button would have bypassed Stage 5 — which §5 says cannot be bypassed — and
   put unreviewed model output in front of an external partner, the §12 Critical risk.
   It is also the better system: choosing the angle is the ownership that makes a partner
   likely to publish. Note the portal shows `title`, `premise` and `audience_value` only —
   `sunreef_relevance` and `score` are internal reasoning and must not reach a broker.
   **Open:** review granularity — one pick yields three drafts, and §5 calls short "a
   condensation of the long form, not a separate piece", so does Stage 5 approve the
   package or each format? Budget is now quantified: ~$0.15 per broker per cycle, under
   $10 for a full 50-broker week, which is what §11.5's missing ceiling should be set
   against. Queue, workers, schema and hosting are still undesigned.
2. **Marketing asset library** (§11.3) — images to pair with drafts. Blocked less on code
   than on §10.7 usage rights: marketing-approved-for-Sunreef is not the same as
   licensed-for-a-broker-to-republish.
3. **Supabase migration** — needed for the portal (auth, Postgres, row-level security).
   Deliberately last: nothing built so far depends on it, and all SQLite-specific code
   lives in one file.
