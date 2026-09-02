# Broker Partner Content Engine

Produces publication-ready articles for Sunreef's broker and dealer partners — written in
each partner's own voice, targeted at search terms they can realistically rank for, and
gated on quality before a human reviews and approves every piece.

The binding design document is
[`docs/superpowers/specs/2026-08-20-broker-partner-content-design.md`](docs/superpowers/specs/2026-08-20-broker-partner-content-design.md).
Read that first — it records not just what the system does but why, including decisions
that were reversed and the reasoning behind them.

## Setting up on a new machine

Requires Python 3.11 or newer.

```bash
git clone <this-repo-url> broker-content-engine
cd broker-content-engine
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The full suite should report **600 passed** and needs no API keys and no network — every
external client is faked in tests. If that passes, the install is good.

## API keys

Two are needed for live runs. Neither is required for tests.

| Variable | Used for | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Angle proposal and drafting | The main dependency — it writes the articles |
| `VOYAGE_API_KEY` | The uniqueness gate | Free tier covers ~385 months at planned volume |

```bash
echo 'export ANTHROPIC_API_KEY="..."' >> ~/.zshrc
echo 'export VOYAGE_API_KEY="..."'    >> ~/.zshrc
source ~/.zshrc
```

**Without `VOYAGE_API_KEY`, every draft is rejected.** That is deliberate, not a bug: the
uniqueness gate is blocking, and a gate that silently degrades to "fine" when it cannot
run is worse than no gate. See §10.3 of the spec.

Keys are read from the environment by the SDKs. Never commit them.

## Running it

```bash
.venv/bin/bce serve
```

Then open <http://localhost:8000>. `bce seed-example` populates example brokers and drafts
so the interface has something to show before any real data exists.

Pipeline commands, roughly in the order they run:

| Command | Does |
|---|---|
| `bce init` | Create the database |
| `bce import <csv>` | Load a broker shortlist |
| `bce qualify` | Check each broker publishes and is in segment |
| `bce profile` | Learn each broker's writing voice |
| `bce keywords <csv>` | Import a Semrush export into the keyword bank |
| `bce draft` | Propose angles and write all three formats |
| `bce serve` | Operator UI |

`bce <command> --help` for options. Anything that spends API budget has a ceiling — see
§11.5 of the spec.

## Keyword bank

The engine selects keywords from a bank imported out of Semrush. To refresh it, export
your research and run `bce keywords <file.csv>`; the importer tolerates the real export
format and reports what qualified and what did not.

[`docs/keyword-research-guide.md`](docs/keyword-research-guide.md) covers what to export
and why. Short version: export your whole considered list rather than pre-filtering — the
import report tells you where the data disagrees with your instinct, which pre-filtering
in Semrush would hide.

## Layout

```
src/bce/
  db.py            schema and migrations — single source of truth
  discover.py      broker shortlist queries
  fetch.py         polite crawling (robots.txt, rate limits)
  detectors.py     segment, editorial and newsletter detection
  articles.py      article extraction
  style.py         voice statistics
  profile.py       voice profiling
  angles.py        angle proposal
  draft.py         the three draft formats
  drafting.py      orchestration and persistence
  keywords.py      keyword bank, gates and selection
  originality.py   the three originality gates
  embeddings.py    Voyage client
  fingerprint.py   shingle fingerprints
  web/             operator UI
docs/              spec, plans, guides, leadership material
data/              keyword exports
```

## Status

Built and tested; never yet run against a real broker. The next step is a live pilot,
which means real crawling and real API spend.

Not yet built: the broker-facing portal (§9b), the marketing asset library (§11.3), and
Supabase migration — in that order, and all after the pilot.
