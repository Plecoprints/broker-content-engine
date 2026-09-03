# Pilot runbook

The order to run things in, what each result means, and where to stop.
Written 2026-09-02, at the point where the pipeline has still never touched a real
broker site.

Read [`STATUS.md`](../STATUS.md) first if you have not. This file assumes it.

---

## The one thing this runbook is for

**Stage A below needs no API key, no budget, and nobody's approval.** It answers the
question that 662 passing tests cannot: *does the crawl-and-read half of this pipeline
survive real broker websites?* Every downstream stage is built on the text Stage A
extracts, so if it comes back thin, nothing after it can be trusted — and you will have
learned that for free.

---

## Stage A — no keys required

### A0. Set the crawler's contact URL

Spec §10.2 requires an identifying User-Agent with a contact URL. The default points at
the Sunreef homepage, which identifies the company but tells a webmaster nothing about
the bot. If you have (or can put up) a page explaining what the crawler is and how to ask
it to stop, point at that instead:

```bash
export BCE_CONTACT_URL='https://www.sunreef-yachts.com/'
```

Not blocking. Worth doing before crawling anyone you want a relationship with.

### A1. Build the broker CSV

Two required columns, `name` and `domain`. `region` is optional and only affects display
order. Headers are matched case-insensitively and tolerate a BOM, so an Excel export
works unchanged. Domains are normalised — `https://www.acme.com/`, `www.acme.com`,
`ACME.com` and `acme.com ` all import identically — so paste whatever you already have.

Template: [`data/broker-import-template.csv`](../data/broker-import-template.csv)

Save yours as `data/brokers.csv`. **That filename is gitignored on purpose** — it is a
list of firms Sunreef is targeting, the repo is public, and `git add -A` is the realistic
way it would leak.

20–30 rows for a first pilot. §6 caps the system at 50 brokers total.

### A2. Create the database and load the keyword banks

```bash
bce init && bce keywords data/keywords-approved.csv && bce exclusions data/keywords-excluded.csv
```

Expect `148 qualify, 0 do not` and `95 excluded keywords loaded`. Anything else means the
banks did not load and you should stop.

### A3. Import the brokers

```bash
bce import data/brokers.csv
```

It reports how many rows imported and names every domain cell it could not parse. Nothing
is skipped silently.

### A4. Qualify — the actual experiment

```bash
bce qualify --limit 30
```

`--limit` defaults to 20, so raise it if your list is longer. This visits each homepage,
honours `robots.txt`, waits 2 seconds between hits on the same host, and identifies
itself. It reads one line per broker.

**The six verdicts:**

| Verdict | Means | What to do |
|---|---|---|
| `passed` | 60ft+ detected, and an editorial section or newsletter found | Nothing — it is in the shortlist |
| `below_length_threshold` | No 60ft+ boat found in the page text | Check a few by hand. This is the verdict a rendering failure produces (see below) |
| `no_publishing_channel` | No editorial URLs found at all | Genuinely no blog. Correct rejection, usually |
| `editorial_stale` | A blog exists, last post is old | A dormant channel, not an absent one. Judgement call |
| `editorial_recency_undetermined` | A blog exists, no date could be read | Worth a manual look; the blog may be fine |
| `unreachable_or_disallowed` | Fetch failed, or `robots.txt` said no | If robots said no, that is a hard no — do not work around it |

### A5. Read the warning line, if there is one

If any page returns almost no visible text, each such line is marked `[!]` and the run
ends with a count. **Take it seriously.** Spec §7 lists Playwright for "JS-rendered sites
(many broker sites are SPA)" — **it is not installed and nothing references it.** The
fetcher is `httpx` only, so a client-rendered site hands back an empty shell, every
detector reads a blank page, and the broker is recorded `below_length_threshold`. That
reads as *"too small for us"* when the truth is *"we could not see the page"*, and it
would quietly delete real brokers from the shortlist.

Open every flagged domain in a browser. Then:

- **One or two flagged** — note them, qualify those by hand, move on.
- **Many flagged** — stop. Rendered fetching is now the next thing to build, and there is
  no point profiling a shortlist assembled from pages nobody could read.

### A6. What you now know

```bash
bce list
```

Whether the crawl-and-read half works, and a real shortlist. **This is the deliverable of
Stage A.** If it looks wrong, the answer is to fix Stage A, not to push on.

---

## Stage B — needs `ANTHROPIC_API_KEY`

```bash
bce profile
```

Learns each broker's voice. Cheap and reversible.

### Then stop. Genuinely stop.

```bash
bce serve   # http://127.0.0.1:8000
```

Read several voice profiles and ask one question: **do these describe brokers you
recognise?** Every draft is built on the profile, so a wrong profile means uniformly wrong
output, produced confidently and at cost. This is the cheapest moment in the whole
pipeline to catch it.

---

## Stage C — needs `ANTHROPIC_API_KEY` and `VOYAGE_API_KEY`

```bash
bce draft
```

Spends real budget: four calls per broker (angles, long, medium, short), capped at 7
brokers per run, roughly $0.15 per broker.

Without `VOYAGE_API_KEY` **every draft is rejected** by design (§10.3) — the uniqueness
gate is blocking and refuses to treat "could not check" as "fine".

Drafts clear the §10.9 gate ensemble automatically. **Operator sampling is 100% for this
first run** — read everything, not to approve it but to see whether the gates behaved.

---

## Things not to do

- **Do not run `draft` before reading profiles.** It is the only step that spends money and
  the only one whose output is worthless if the step before it was wrong.
- **Do not work around a `robots.txt` refusal.** §10.2, and it is a partner relationship.
- **Do not commit `data/brokers.csv`.** Gitignored, but the repo is public.
- **Do not send anything to a broker.** §10.1's legal review on advertising disclosure is
  blocking before first outreach and has not happened. Drafting and reviewing are fine;
  sending is not.
