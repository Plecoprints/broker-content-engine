# Keyword research → keyword bank

How to get keywords out of Semrush and into the content engine.

## The short version

Export a CSV from Semrush. Drop it anywhere. Run:

```bash
bce keywords import ~/Downloads/your-export.csv
```

The importer reports what qualified, what didn't, and why.

## What to export

**Any Semrush keyword export works.** Keyword Magic Tool, Keyword Overview, a saved keyword list —
the importer matches column headers case-insensitively and ignores columns it doesn't need.

**The two columns that must be present:**

| Column | Also accepted as |
|---|---|
| Keyword | `phrase` |
| Keyword Difficulty | `KD`, `Keyword Difficulty Index`, `difficulty` |

**Strongly wanted:**

| Column | Why |
|---|---|
| Volume / Search Volume | Half of the qualifying test. Without it nothing can qualify. |
| Intent | Informational keywords make better articles; transactional ones make better broker landing pages. |

Everything else — CPC, competitive density, SERP features, trend, results — is ignored. Leave it in;
it costs nothing.

## The bar a keyword has to clear

To be **automatically baked into a draft**, a keyword needs both:

- **Keyword difficulty below 30**
- **Average monthly search volume above 100**

## Export everything you think is worth considering, not just what clears the bar

Do not pre-filter to the thresholds. Export your full considered list.

Keywords that miss the bar are still imported and still visible — they're just not selected
automatically. The import report tells you the split:

```
Imported 214 keywords (203 new, 11 updated)
  152 qualify
   62 do not:
        41 difficulty too high (>= 30)
        19 volume too low (<= 100)
         2 both
   12 competitor brand — gated, needs explicit opt-in
    3 rows skipped (unparsable) — listed below
```

That report is the point of doing this. It tells you what your research actually yielded, and it
tells you which of your instincts the data disagrees with.

## Why the thresholds are what they are

A partner broker doesn't have Sunreef's domain authority. An article aimed at `luxury yacht charter`
(8,100 searches, KD 60) will not rank, so it's an article wasted — it produces no traffic for the
broker and no reason for them to keep publishing us.

The good news from the initial research: **catamarans specifically are far less contested than the
luxury-yacht space around them.** `catamaran for sale` is 8,100 searches at KD 25. `power catamaran
for sale` is 2,400 at KD 17. `yacht refit` is 1,900 at KD 10. There is winnable volume in exactly
the category Sunreef occupies.

## How many keywords a draft uses

Keyword load scales with length — about one per 500 words. Past that it reads like stuffing.

| Format | Primary | Secondary |
|---|---|---|
| Long (2,000–2,300 words) | 1 | up to 4 |
| Medium (broker's typical length) | 1 | up to 2 |
| Short (newsletter, 100–200 words) | 1 | — |

Medium and short are condensations of the long draft, so their keywords are always a subset of the
long draft's.

## Two things to decide when you export

**Region.** Volume differs substantially by Semrush database. The initial bank was measured against
**US**. If your brokers skew Mediterranean or Caribbean, export from the databases that match them —
the region is stored per keyword, so US and UK data can coexist in the bank.

**Competitor brands.** Semrush's semantic expansion will surface Sunreef's rivals — Lagoon, Leopard,
Aquila, Fountaine Pajot, Bali and others — and they often pass both filters easily. These are
detected on import and **gated**: stored, visible, never auto-selected. Ranking a partner broker for
a rival's brand name is a defensible comparison play or an own goal depending on your read, so it
takes an explicit human decision rather than the engine's.

## Re-exporting later

Safe. Re-importing the same file changes nothing, and importing an updated export refreshes metrics
on keywords already in the bank rather than duplicating them.

Every keyword stores the date it was measured, and every figure shown in the UI carries that date.
A keyword at KD 28 today can be KD 32 next quarter — the system will never present a cached number
as though it were current.
