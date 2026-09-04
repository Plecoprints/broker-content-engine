# PRD — Broker Content Engine (UI elevation)

## Original problem statement
"Look at this repo so I can determine how to elevate the UI." Then: "Take the design
logic from https://sunreef-catamarans.com/en/80-power-next/ and apply it."

## Architecture (existing)
- Python 3.11 · FastAPI + Jinja2 + HTMX (no build step, by design — spec design handover).
- CLI (`bce ...`): init / import / qualify / profile / keywords / draft / serve / seed-example.
- Operator UI served by `bce serve` on 127.0.0.1:8000. Reads SQLite directly. Localhost,
  optional HTTP-Basic via `BCE_OPERATOR_PASSWORD` (none set here — no auth on loopback).
- Two UI surfaces: internal **Operator UI** (`src/bce/web/templates/`) and an external
  **Broker portal prototype** (`design/broker-portal-prototype.html`, not wired up).

## What was done (2026-06 / this session)
- **Elevated the Operator UI** using the Sunreef 80 Power NEXT design logic + the repo's own
  brand tokens (`docs/leadership-brief.html`): Bodoni Moda display with brass italic accents,
  IBM Plex Mono uppercase labels, Archivo body; warm paper/ink/brass palette with
  signal-teal / locked-terracotta / brass-amber verdict marks; big-number stat grid;
  hairline tables; cinematic dark abyss masthead with brass rule.
- Full **light + dark** support (system preference + a persisted toggle in the masthead).
- Rewrote `base.html`, `shortlist.html`, `add.html`, `draft_viewer.html`. Left the two
  reusable macros (`_keyword_panel.html`, `_gate_panel.html`) untouched — they inherit the
  new styling and their copy is asserted verbatim by the web tests.
- Added `data-testid` attributes across interactive/informational elements.
- Preserved all routes, CSRF token placement, exact copy strings, class names
  (`keyword-panel`/`empty-state`/`pill-*`), and the "no literal None leaks" guarantee.

## Iteration 2 (this session) — portal + HTMX + reading view
- **Broker portal is now live** at `GET /portal` (`templates/portal.html`) — its own broker-first
  identity (Fraunces serif, teal accent, broker firm as masthead, Sunreef credited quietly via a
  provenance strip; Sunreef brass used ONLY for the delivered/archive tag). Honors §9b hard rules:
  no `score`, no `sunreef_relevance`, no Semrush figures (keyword phrases only). Slate is a curated
  demo (`_PORTAL_SLATE` in app.py — queue/schema still undesigned); "Collected" is driven by the
  real seeded broker + drafts.
- **HTMX turned on** — vendored locally at `src/bce/web/static/htmx.min.js`, mounted at `/static`.
  Add-broker forms `hx-post` and swap an in-place feedback fragment (`_add_feedback.html`) via the
  new `_result()` helper (branches on the `HX-Request` header). Non-HTMX posts still 303-redirect,
  so every existing test is untouched.
- **Draft reading view** — `draft_viewer.html` now has Pillar/Regular/Newsletter tabs (switch in
  place; all three still rendered server-side so tests pass), a narrower reading column, and a
  one-tap Copy per draft. New `GET /portal/download/{draft_id}` serves a draft as a .txt attachment;
  portal Copy/Download buttons use it.

## Verification
- Full suite green after both iterations: **755 passed** (no network, no API keys).
- Curl-verified: `/portal` 200, `/static/htmx.min.js` 200, `/portal/download/1` 200, HTMX manual-add
  returns the feedback fragment with updated count.
- Visual pass in light + dark for: shortlist, add (HTMX in-place), draft viewer (tabs + copy),
  portal (slate + collected).
- NOTE: no automated browser test run — app serves on `localhost:8000` via CLI (not the standard
  preview port), so verification is the passing unit suite + curl + screenshots.

## Iteration 4 (this session) — preview wiring + "Soft Machine" neumorphic redesign
- **Preview now works**: repo has no /app/frontend|backend, so default supervisor programs are FATAL.
  Added a `bce` supervisor program (`/etc/supervisor/conf.d/bce.conf`, recoverable copy in
  `/app/scripts/`) running `uvicorn bce.web.asgi:app` on :3000 (the port the platform preview
  proxies) with --reload; new `src/bce/web/asgi.py` factory; `_TEMPLATES.env.auto_reload=True`.
  Re-enable after a pod restart: `bash /app/scripts/enable_preview.sh`.
- **Operator console fully re-skinned as neumorphic soft-UI** (user brief: clinical luxury, Apple ×
  Sunreef × Rolls-Royce × Richard Mille × Abloh; reference images + exact shadow specs supplied).
  One material `#E8EAE9`, depth from paired `#FFFFFF` / navy `#0D2750` shadows only (no borders);
  single Richard-Mille red accent; Manrope (thin display) + IBM Plex Mono microlabels; metallic
  knurled theme toggle; raised/inset elevation tokens; graphite dark variant. Rewrote `base.html`
  CSS (all shared class hooks preserved so page templates + the 755 tests are unaffected).
- Design agent NOT used (user supplied explicit images + shadow values, per policy).

## Backlog / next
- P0 (still pending from iteration-3 ask): Portal sign-in (single-use invite link + session),
  angle persistence into a review queue, portal empty/"week skipped" states, voice-profile page.
  Integration playbook for the invite-link/session auth already obtained; schema plan drafted
  (broker_invite, broker_session, slate_angle, review_pick).
- P1: Carry the soft-UI/neumorphic system across to the broker portal (its own broker-first palette).
- P1: Apply the same system to the external **broker portal** — but per `design/README.md`
  the portal must NOT read as Sunreef marketing (brass hidden, broker masthead). Distinct job.
- P1: Wire HTMX partial-swaps (base.html notes it's not yet added).
- P2: Draft viewer reading polish (typographic scale, copy-to-clipboard on drafts).
- P2: Empty/pending states beyond the seeded examples; mobile refinement of the wide table.
