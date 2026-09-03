# Broker portal — design handover

For the creative director taking this to GTM.

`broker-portal-prototype.html` is the starting point: one screen, self-contained, open it in
any browser. `explorations/` holds two rejected directions, kept for context on the space
rather than as options.

---

## What this screen is

The **weekly slate**. Once a week a broker is told new article angles are waiting. They sign
in, see 3–5 proposed angles, and pick one. That pick produces three pieces written in their
own voice — a ~2,000 word pillar, a medium post, a short newsletter item — which they publish
under **their own byline on their own site**.

The slate is **fixed for the week**. No reroll, no regenerate button. That is a deliberate
product decision, not a missing feature (spec §9b).

## Who is looking at it

An independent yacht broker who sells many manufacturers, not just Sunreef. Time-poor,
commercially sharp, protective of their masthead and their credibility with clients. **They did
not ask for this.** Sunreef holds no ongoing agreement with them — a broker signs a single-deal
agreement only when they bring an active referral.

## The design problem, which is the whole job

This must not feel like a manufacturer's marketing portal, because a broker who feels marketed
to will not publish. It has to read as a genuinely useful editorial tool that happens to be
provided by Sunreef. The content is theirs. The decision is theirs. Sunreef should read as a
credible source standing behind it, not a brand extracting placement.

Get that wrong and the programme fails regardless of how good the writing is.

Two choices in the prototype that serve this, worth keeping or beating deliberately rather
than removing by accident:

- **Sunreef's brand accent `--brass` is not used.** A manufacturer's brand colour on a broker's
  editorial desk is the exact signal to avoid.
- **The masthead is the broker's own firm.** Sunreef is credited once, quietly, like a
  publisher's imprint.

---

## Hard rules

**1. Never display `sunreef_relevance` or `score`.**

Each angle carries five fields. Three are shown: `title`, `premise`, `audience_value`. Two are
internal and must never reach a broker:

- `sunreef_relevance` is literally *"how this connects to catamaran ownership without reading as
  an advertisement."* A broker reading that sentence sees the machinery behind their own
  editorial calendar.
- `score` is a numeric publishability rank on content pitched to them as tailored.

This is a correctness rule, not a preference. It is checked in review.

**2. No Semrush figures anywhere in the UI.**

Search volume, keyword difficulty, CPC. Our Semrush licence permits internal use only — these
files are not for redistribution, and this screen goes in front of external partners. Keyword
*phrases* are fine; the numbers are not.

**3. No build step.**

Plain HTML and CSS. This becomes a Jinja2 template with HTMX for interactivity (spec §7). No
npm, no bundler, no React, Vue or Tailwind. Fonts from Google Fonts only. That constraint is
what keeps the whole system deployable as one Python process — please design within it rather
than around it.

**4. Light and dark both have to work.**

Declare the complete light palette on bare `:root`. Redefine only the tokens under
`@media (prefers-color-scheme: dark)`, guarded as `:root:not([data-theme="light"])`, and again
under `:root[data-theme="dark"]`. `body` sets an explicit background from a token. A colour
whose only definition sits inside a media or `[data-theme]` block will not apply in the
default state, which is the common way these pages break.

---

## Context worth reading

- `docs/leadership-brief.html` — Sunreef's existing visual identity. Its `:root` tokens
  (`--abyss`, `--hull`, `--paper`, `--brass`, `--signal`) and typefaces (Bodoni Moda / Archivo /
  IBM Plex Mono). The prototype extends this; whether Bodoni belongs in the portal is still an
  open question you are welcome to settle.
- `docs/superpowers/specs/2026-08-20-broker-partner-content-design.md` §9b — the portal model,
  the field-visibility split, and the invite-link credential flow.
- `src/bce/web/templates/` — the internal operator UI. Deliberately plainer. **Not** a reference
  for this surface.

## Not designed yet

Only the weekly slate exists. Still open:

- Sign-in, from a single-use invite link (never an emailed password)
- The collect screen — where a broker takes the three finished formats
- The copy/download interaction, including the line telling brokers that usage is tracked
- Empty states: no angles yet, a week skipped, nothing published
- Mobile
