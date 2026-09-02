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
| Keyword bank, four selection gates | Done |
| Angle proposal and three-format drafting | Done |
| Three originality gates (§10.3) | Done |
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
bce import <brokers.csv>
bce qualify      # visits sites, respects robots.txt — cheap, reversible
bce profile      # learns each voice — cheap, reversible
# STOP. Read several voice profiles in the UI and check they describe brokers you
# recognise. If profiling is wrong, every draft built on it is wrong too.
bce draft        # spends real API budget; capped at 7 brokers per run
```

## Decisions that would otherwise surprise you

- **Long drafts are not blocked on voice match.** Voice matching is binding for medium and
  short, advisory for the 2,000–2,300 word pillar. No broker's typical article length is
  near 2,000 words, so a blocking check would fail every pillar.
- **`tailored_score` of `NULL` means "not comparable", not zero.** A broker profiled with a
  register but no writing statistics gets NULL and is not blocked.
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

1. **Broker-facing portal** (§9b) — partner logins, row-level security. A strong idea
   surfaced late: let brokers pick from proposed angles rather than receiving finished
   articles unprompted. A partner who chose the topic is far likelier to publish it.
2. **Marketing asset library** (§11.3) — images to pair with drafts. Blocked less on code
   than on §10.7 usage rights: marketing-approved-for-Sunreef is not the same as
   licensed-for-a-broker-to-republish.
3. **Supabase migration** — needed for the portal (auth, Postgres, row-level security).
   Deliberately last: nothing built so far depends on it, and all SQLite-specific code
   lives in one file.
