# Operator UI Implementation Plan (Stage 5 surface, partial)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local web interface where an operator can see the broker shortlist and each broker's voice profile, running on `localhost:8000` against the existing SQLite database.

**Architecture:** FastAPI serving Jinja2 templates, with HTMX for partial updates. It imports `bce.discover` and `bce.db` directly — no API layer, no serialization boundary, no build step. Task 1 is a vertical slice: a runnable server showing real shortlist rows. Later tasks add screens against the same app.

**Tech Stack:** Python 3.11.9, FastAPI, uvicorn, Jinja2, HTMX (script tag), pytest + `fastapi.testclient`

**Spec:** `docs/superpowers/specs/2026-08-20-broker-partner-content-design.md` (v0.5) — §9 defines this surface.

## Global Constraints

- **Localhost only, no auth** (§9). Single operator, one machine. Auth is required before this is exposed to anyone else; do not add a half-measure.
- **Never destructive without confirmation** (§9). Rejecting archives; nothing is hard-deleted.
- **Affinity is ordering-only** (§2, §4). Every broker `list_brokers` returns must be displayed. No filtering, grouping, or visual tiering by affinity — sorting the list is fine, hiding or badging a broker as lesser is not.
- **No network, no API key, in the app or its tests.** The UI reads SQLite. It must not call Claude, fetch broker sites, or reach Semrush.
- **The review queue is NOT in this plan.** It reviews drafts, and Stage 4 does not exist yet. Do not stub it.
- Four fields are JSON strings that templates must parse: `voice_profile.themes`, `vocabulary_markers`, `sample_quotes`, and `structure_pattern`. **`structure_pattern` is `{"paragraphs_per_article": N|null, "words_per_paragraph": M|null}`** — both keys can be null.
- **Every rendered field can be NULL.** A broker may have no voice profile at all; a profiled broker may have NULL `register`/`themes`/`audience_signal` because classification failed (`bce.profile.ProfileResult.classified` is False). Rendering must degrade, never raise.
- Example data uses `.invalid` domains — a reserved TLD that can never resolve, so seed data can never be mistaken for or accidentally crawled as a real broker.
- No new runtime dependency beyond `fastapi`, `uvicorn[standard]`, `jinja2`.

---

### Task 1: Runnable vertical slice — server, shortlist page, example data

The point of this task is that it **runs and shows something**. Scaffolding without a visible page is a failed task.

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bce/web/__init__.py`, `src/bce/web/app.py`
- Create: `src/bce/web/templates/base.html`, `src/bce/web/templates/shortlist.html`
- Create: `src/bce/seed.py`
- Modify: `src/bce/cli.py` (add `serve` and `seed-example`)
- Test: `tests/test_web_shortlist.py`, `tests/test_seed.py`

**Interfaces:**
- Consumes: `bce.db.connect`, `bce.db.init_schema`, `bce.discover.list_brokers`
- Produces:
  - `bce.seed.seed_example(conn) -> int` — inserts example brokers covering **every display state**, returns count
  - `bce.web.app.create_app(db_path: str) -> FastAPI`
  - `GET /` → the shortlist page
  - `cli.cmd_serve(db_path, host="127.0.0.1", port=8000) -> int`
  - `cli.cmd_seed_example(db_path) -> int`

**The seed data must exercise the edge states, not the happy path.** This is the lesson from Stage 3: a fixture that only shows the clean case produces code that looks correct until real data arrives. Include at minimum:

| Example broker | State it exercises |
|---|---|
| Qualified, profiled, classified | The full happy path |
| Qualified, profiled, **classification failed** | NULL `register`/`themes`/`audience_signal` with statistics present |
| Qualified, **not yet profiled** | No `voice_profile` row at all |
| Rejected — `below_length_threshold` | A rejection reason |
| Rejected — `editorial_recency_undetermined` | The reason Stage 3 added |
| Rejected — `unreachable_or_disallowed` | NULL channel columns (`_tri` writes NULL for "never looked") |
| Pending (`qualified IS NULL`) | Never run through Stage 2 |
| One with `sunreef_affinity = 'lists_inventory'`, one `'none'` | Ordering, and that neither is hidden or badged |

- [ ] **Step 1: Write the failing test**

`tests/test_seed.py`:
```python
from bce import db, discover, seed


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    return c


def test_seed_covers_every_display_state():
    conn = _conn()
    n = seed.seed_example(conn)
    assert n >= 7
    rows = discover.list_brokers(conn)
    reasons = {r["qualified_reason"] for r in rows}
    assert {"below_length_threshold", "editorial_recency_undetermined",
            "unreachable_or_disallowed"} <= reasons
    assert any(r["qualified"] is None for r in rows)
    assert any(r["qualified"] == 1 for r in rows)


def test_seed_includes_a_profiled_broker_whose_classification_failed():
    conn = _conn()
    seed.seed_example(conn)
    row = conn.execute(
        "SELECT * FROM voice_profile WHERE register IS NULL"
    ).fetchone()
    assert row is not None
    assert row["avg_sentence_len"] > 0


def test_seed_includes_a_qualified_broker_with_no_profile():
    conn = _conn()
    seed.seed_example(conn)
    row = conn.execute(
        "SELECT b.id FROM broker b LEFT JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND v.broker_id IS NULL"
    ).fetchone()
    assert row is not None


def test_every_seed_domain_is_unresolvable():
    """`.invalid` is reserved by RFC 2606 — seed data can never be crawled."""
    conn = _conn()
    seed.seed_example(conn)
    for row in discover.list_brokers(conn):
        assert row["domain"].endswith(".invalid")


def test_seed_is_idempotent():
    conn = _conn()
    seed.seed_example(conn)
    first = len(discover.list_brokers(conn))
    seed.seed_example(conn)
    assert len(discover.list_brokers(conn)) == first
```

`tests/test_web_shortlist.py`:
```python
from fastapi.testclient import TestClient

from bce import db, seed
from bce.web.app import create_app


def _client(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    conn.close()
    return TestClient(create_app(path))


def test_shortlist_page_renders(tmp_path):
    r = _client(tmp_path).get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_shortlist_shows_every_broker(tmp_path):
    client = _client(tmp_path)
    body = client.get("/").text
    conn = db.connect(str(tmp_path / "ui.db"))
    from bce import discover
    for row in discover.list_brokers(conn):
        assert row["name"] in body, f"{row['name']} missing from the page"


def test_shortlist_shows_rejection_reasons(tmp_path):
    body = _client(tmp_path).get("/").text
    assert "below_length_threshold" in body


def test_shortlist_renders_a_broker_with_no_profile_without_erroring(tmp_path):
    """Half the seed rows have NULLs somewhere. None may raise."""
    assert _client(tmp_path).get("/").status_code == 200


def test_empty_database_renders_an_empty_state(tmp_path):
    path = str(tmp_path / "empty.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    r = TestClient(create_app(path)).get("/")
    assert r.status_code == 200
    assert "no brokers" in r.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_seed.py tests/test_web_shortlist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bce.seed'` and `'bce.web'`.

- [ ] **Step 3: Write minimal implementation**

Add to `pyproject.toml` dependencies:
```toml
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.30,<1.0",
    "jinja2>=3.1,<4.0",
```

`src/bce/seed.py` — example data covering the table above. Every domain ends `.invalid`. Make it idempotent by checking for an existing marker domain before inserting. Insert `voice_profile` rows directly with `json.dumps` for the four JSON columns, matching what `bce.profile` writes.

`src/bce/web/app.py`:
```python
"""Operator UI (spec §9). Localhost only, no auth, reads SQLite directly."""
import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from bce import db, discover

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _loads(value, default):
    """JSON columns may be NULL or malformed; never raise while rendering."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Broker Content Engine")
    app.state.db_path = db_path
    _TEMPLATES.env.filters["fromjson"] = lambda v: _loads(v, None)

    @app.get("/", response_class=HTMLResponse)
    def shortlist(request: Request):
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)
        brokers = discover.list_brokers(conn)
        return _TEMPLATES.TemplateResponse(
            request=request, name="shortlist.html",
            context={"brokers": brokers},
        )

    return app
```

`src/bce/web/templates/base.html` — a minimal page shell with the HTMX script tag from a CDN comment (do NOT add a network dependency the app needs to function; HTMX is not used until a later task, so leave the tag out for now and note it).

`src/bce/web/templates/shortlist.html` — extends base, one row per broker showing name, domain, region, affinity, state (qualified/rejected/pending), reason, and which channels were found. Use `{% if %}` guards for every nullable field. Show an empty state containing the words "no brokers" when the list is empty.

Add to `src/bce/cli.py`:
```python
def cmd_seed_example(db_path: str) -> int:
    conn = db.connect(db_path)
    db.init_schema(conn)
    print(f"seeded {seed.seed_example(conn)} example brokers (.invalid domains)")
    return 0


def cmd_serve(db_path: str, host: str = "127.0.0.1", port: int = 8000) -> int:
    import uvicorn
    from bce.web.app import create_app
    print(f"http://{host}:{port}")
    uvicorn.run(create_app(db_path), host=host, port=port, log_level="warning")
    return 0
```
Wire both into `main`'s subparsers. **`uvicorn` is imported inside the function**, not at module scope, so the CLI's other commands do not pay for it and the test suite never starts a server.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pip install -q -e ".[dev]" && .venv/bin/python -m pytest tests/ -v`
Expected: PASS — 268 prior plus the new ones.

Then confirm it actually runs, which is this task's whole point:
```bash
.venv/bin/bce --db /tmp/ui-demo.db seed-example
.venv/bin/bce --db /tmp/ui-demo.db serve
```
Open `http://127.0.0.1:8000`. **Report what you see** — how many brokers rendered, and whether the NULL-heavy rows display sensibly or look broken. A page that renders without raising but shows "None" in six columns has passed its tests and failed its purpose; say so if that is what you find.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/bce/seed.py src/bce/web src/bce/cli.py tests/test_seed.py tests/test_web_shortlist.py
git commit -m "feat: operator UI vertical slice — shortlist page with example data"
```

---

### Task 2: Add brokers — CSV upload and manual entry

**Added after operator review of Task 1.** The shortlist page was read-only: the only way to get brokers
in was `bce import` at a terminal, which is a developer tool, not an operator one. This is the blocking
usability gap and it comes before everything else.

**Files:**
- Modify: `src/bce/web/app.py`
- Create: `src/bce/web/templates/add.html`
- Modify: `src/bce/web/templates/shortlist.html` (link to the add page), `base.html` (nav)
- Test: `tests/test_web_add.py`

**Interfaces:**
- Consumes: `bce.discover.import_csv`, `discover.count_new_domains`, `discover.CsvHeaderError`, `bce.cli.MAX_BROKERS`
- Produces:
  - `GET /add` → the form page
  - `POST /add/csv` → multipart upload; redirects to `/` on success
  - `POST /add/manual` → form fields `name`, `domain`, optional `region`; redirects to `/` on success

**Reuse the existing pipeline logic; do not reimplement any of it.** `import_csv` already handles
case-insensitive headers, the UTF-8 BOM, whitespace-padded header names, domain normalization
(scheme/path/`www.` stripping), and duplicate-domain skipping. `count_new_domains` already counts only
domains not already present. Rewriting any of that in the web layer would create a second source of
truth for rules that took two fix rounds to get right.

**Four behaviours the page must get right:**

1. **The §6 cap refuses, it does not truncate.** If `existing + new > MAX_BROKERS`, reject the whole
   upload with a message naming both numbers — the same discipline as `cmd_import`. Silently importing
   the first 50 of 55 hides that the operator crossed the line.
2. **A bad CSV header must say what it found.** `import_csv` raises `CsvHeaderError` carrying the headers
   actually present. Surface those. "Imported 0 brokers" for a `Name,Domain` file is the exact
   silent-no-op this project already fixed once at the CLI; do not reintroduce it in the UI.
3. **Manual add validates the domain** through the same normalization, and reports a cell that is not a
   hostname rather than storing it. A URL in the domain field caused permanent false rejections in
   Stage 2; the form is where to catch it.
4. **Feedback is specific.** "Imported 12 brokers (3 duplicates skipped)" — not "success".

- [ ] **Step 1: Write the failing test**

`tests/test_web_add.py`:
```python
import io

from fastapi.testclient import TestClient

from bce import cli, db, discover
from bce.web.app import create_app


def _client(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    conn.close()
    return TestClient(create_app(path)), path


def _csv(text):
    return {"file": ("brokers.csv", io.BytesIO(text.encode()), "text/csv")}


def test_add_page_renders(tmp_path):
    client, _ = _client(tmp_path)
    r = client.get("/add")
    assert r.status_code == 200
    assert "csv" in r.text.lower()


def test_csv_upload_imports_brokers(tmp_path):
    client, path = _client(tmp_path)
    r = client.post("/add/csv", files=_csv("name,domain\nAcme,acme.invalid\n"),
                    follow_redirects=True)
    assert r.status_code == 200
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1


def test_csv_upload_tolerates_title_case_headers(tmp_path):
    """The exact silent no-op fixed at the CLI — it must not return in the UI."""
    client, path = _client(tmp_path)
    client.post("/add/csv", files=_csv("Name,Domain\nAcme,acme.invalid\n"),
                follow_redirects=True)
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1


def test_bad_headers_report_what_was_found(tmp_path):
    client, _ = _client(tmp_path)
    r = client.post("/add/csv", files=_csv("company,website\nAcme,acme.invalid\n"),
                    follow_redirects=True)
    assert "company" in r.text and "website" in r.text


def test_cap_refuses_the_whole_upload(tmp_path):
    client, path = _client(tmp_path)
    rows = "name,domain\n" + "".join(f"B{i},b{i}.invalid\n" for i in range(cli.MAX_BROKERS + 5))
    r = client.post("/add/csv", files=_csv(rows), follow_redirects=True)
    assert "cap" in r.text.lower()
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0, "refusal must insert nothing"


def test_manual_add_creates_a_broker(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/manual", data={"name": "Acme", "domain": "acme.invalid",
                                     "region": "Med"}, follow_redirects=True)
    conn = db.connect(path)
    rows = discover.list_brokers(conn)
    assert len(rows) == 1 and rows[0]["region"] == "Med"


def test_manual_add_normalizes_a_url_in_the_domain_field(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/manual", data={"name": "Acme", "domain": "https://www.acme.invalid/"},
                follow_redirects=True)
    conn = db.connect(path)
    assert discover.list_brokers(conn)[0]["domain"] == "acme.invalid"


def test_manual_add_rejects_a_non_hostname(tmp_path):
    client, path = _client(tmp_path)
    r = client.post("/add/manual", data={"name": "Acme", "domain": "not a domain"},
                    follow_redirects=True)
    assert "not a domain" in r.text
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 0


def test_duplicate_domain_is_reported_not_silently_dropped(tmp_path):
    client, path = _client(tmp_path)
    client.post("/add/csv", files=_csv("name,domain\nAcme,acme.invalid\n"), follow_redirects=True)
    r = client.post("/add/csv", files=_csv("name,domain\nAcme Again,acme.invalid\n"),
                    follow_redirects=True)
    assert "0" in r.text
    conn = db.connect(path)
    assert len(discover.list_brokers(conn)) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_add.py -v`
Expected: FAIL — 404 on `/add`, since no route exists. `python-multipart` may also be missing; if the
upload tests error on that rather than 404, add it as a dependency and say so.

- [ ] **Step 3: Write minimal implementation**

Add the three routes to `create_app`. Carry the result message across the redirect (a query parameter is
fine at this scale; do not add a session). Catch `CsvHeaderError` and render its headers. Check the cap
with `count_new_domains` **before** inserting.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`

Then **use the page yourself**: start the server, upload a CSV with Title-Case headers, try one over the
cap, and add one manually with a URL in the domain field. Report what each one showed you. A form that
passes its tests but gives an operator no idea what happened has failed this task.

- [ ] **Step 5: Commit**

```bash
git add src/bce/web tests/test_web_add.py
git commit -m "feat: add brokers via CSV upload and manual entry"
```

---

## Deferred until after Stage 4

The two tasks below are written and ready, but the operator's priority is seeing **article content**,
which does not exist until Stage 4 (drafting) is built. Broker detail and the dashboard are informative
rather than blocking, so they wait. The review queue — §9's core screen, where article options are
compared and approved — also belongs to that later pass, since it reviews drafts.

---

### Task 3 (deferred): Broker detail with the voice profile

**Files:**
- Modify: `src/bce/web/app.py`
- Create: `src/bce/web/templates/broker.html`
- Modify: `src/bce/web/templates/shortlist.html` (link each row)
- Test: `tests/test_web_broker.py`

**Interfaces:**
- Produces: `GET /broker/{broker_id}` → detail page; 404 for an unknown id

Renders the qualification evidence (reason, channels, `editorial_last_post`, affinity evidence, segment evidence) and the full voice profile: register, audience signal, themes, vocabulary markers, sample quotes, and the four statistics.

**Three rendering traps, all of which will occur in the seed data:**
1. `structure_pattern` is JSON with two keys that **can both be null** — `{"paragraphs_per_article": null, "words_per_paragraph": null}`. Render "unknown" rather than "None".
2. A profiled broker whose classification failed has NULL `register`/`audience_signal` and `[]` for the lists. Say "classification failed" rather than showing blanks.
3. A broker with **no `voice_profile` row at all** must render the page with a "not yet profiled" state, not 404 and not an exception.

- [ ] **Step 1: Write the failing test**

`tests/test_web_broker.py`:
```python
from fastapi.testclient import TestClient

from bce import db, discover, seed
from bce.web.app import create_app


def _setup(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    return path, conn


def _id_where(conn, sql):
    return conn.execute(sql).fetchone()["id"]


def test_detail_renders_a_full_profile(tmp_path):
    path, conn = _setup(tmp_path)
    bid = _id_where(conn, "SELECT b.id FROM broker b JOIN voice_profile v "
                          "ON v.broker_id=b.id WHERE v.register IS NOT NULL")
    body = TestClient(create_app(path)).get(f"/broker/{bid}").text
    assert "register" in body.lower()


def test_detail_renders_a_broker_with_no_profile(tmp_path):
    path, conn = _setup(tmp_path)
    bid = _id_where(conn, "SELECT b.id FROM broker b LEFT JOIN voice_profile v "
                          "ON v.broker_id=b.id WHERE v.broker_id IS NULL")
    r = TestClient(create_app(path)).get(f"/broker/{bid}")
    assert r.status_code == 200
    assert "not yet profiled" in r.text.lower()


def test_detail_says_classification_failed_rather_than_showing_blanks(tmp_path):
    path, conn = _setup(tmp_path)
    bid = _id_where(conn, "SELECT b.id FROM broker b JOIN voice_profile v "
                          "ON v.broker_id=b.id WHERE v.register IS NULL")
    body = TestClient(create_app(path)).get(f"/broker/{bid}").text
    assert "classification failed" in body.lower()


def test_detail_never_prints_the_word_none(tmp_path):
    """A NULL rendered as the literal 'None' is a bug the tests must catch."""
    path, conn = _setup(tmp_path)
    client = TestClient(create_app(path))
    for row in discover.list_brokers(conn):
        body = client.get(f"/broker/{row['id']}").text
        assert ">None<" not in body, f"raw None rendered for {row['name']}"


def test_unknown_broker_is_404(tmp_path):
    path, _ = _setup(tmp_path)
    assert TestClient(create_app(path)).get("/broker/99999").status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_broker.py -v`
Expected: FAIL — 404 on every detail URL, since the route does not exist.

- [ ] **Step 3: Write minimal implementation**

Add the route to `create_app`, joining `broker` and `voice_profile` with a LEFT JOIN so a missing profile yields NULLs rather than no row. Parse the four JSON columns through `_loads` with `[]`/`{}` defaults. Template guards every field.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: PASS. Then reload the running server and **report what the three states actually look like**.

- [ ] **Step 5: Commit**

```bash
git add src/bce/web tests/test_web_broker.py
git commit -m "feat: broker detail page with voice profile"
```

---

### Task 4 (deferred): Dashboard

**Files:**
- Modify: `src/bce/web/app.py`, `src/bce/web/templates/base.html`
- Create: `src/bce/web/templates/dashboard.html`
- Modify: `src/bce/discover.py` (add `pipeline_counts`)
- Test: `tests/test_web_dashboard.py`

**Interfaces:**
- Produces: `discover.pipeline_counts(conn) -> dict` with keys `total`, `pending`, `qualified`, `rejected`, `profiled`, `awaiting_profile`, `classification_failed`; `GET /dashboard` renders them

`awaiting_profile` must match what `unprofiled_brokers` would return — qualified with no profile row. `classification_failed` counts profiled brokers with NULL `register`. Add a test asserting `pipeline_counts` and `unprofiled_brokers` agree, so the dashboard cannot drift from the queue it describes.

- [ ] **Step 1: Write the failing test**

`tests/test_web_dashboard.py`:
```python
from fastapi.testclient import TestClient

from bce import db, discover, seed
from bce.web.app import create_app


def _conn():
    c = db.connect(":memory:")
    db.init_schema(c)
    seed.seed_example(c)
    return c


def test_counts_sum_to_total():
    counts = discover.pipeline_counts(_conn())
    assert counts["pending"] + counts["qualified"] + counts["rejected"] == counts["total"]


def test_awaiting_profile_agrees_with_the_queue():
    """The dashboard must not drift from the queue it describes."""
    conn = _conn()
    counts = discover.pipeline_counts(conn)
    assert counts["awaiting_profile"] == len(discover.unprofiled_brokers(conn, 1000))


def test_classification_failed_is_counted():
    assert discover.pipeline_counts(_conn())["classification_failed"] >= 1


def test_dashboard_page_renders(tmp_path):
    path = str(tmp_path / "ui.db")
    conn = db.connect(path)
    db.init_schema(conn)
    seed.seed_example(conn)
    conn.close()
    r = TestClient(create_app(path)).get("/dashboard")
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_web_dashboard.py -v`
Expected: FAIL — `AttributeError: module 'bce.discover' has no attribute 'pipeline_counts'`.

- [ ] **Step 3: Write minimal implementation**

`pipeline_counts` as a single query per count or one aggregate — your choice, but `awaiting_profile` must use the same LEFT JOIN predicate as `unprofiled_brokers` so the equality test is structural, not coincidental. Add nav links in `base.html`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/ -v`

- [ ] **Step 5: Commit**

```bash
git add src/bce/web src/bce/discover.py tests/test_web_dashboard.py
git commit -m "feat: pipeline dashboard"
```

---

## Self-Review

**1. Spec coverage.** §9's Dashboard → Task 3; Shortlist → Task 1; Broker detail → Task 2. **Deliberately absent:** the Review queue, Outreach, and Outcomes screens, because all three operate on drafts and Stage 4 does not exist. Stubbing them would produce empty shells that look like features. §9's auth constraint is honoured by having none and saying so.

**2. Placeholder scan.** No TBDs. Task 1's step 4 requires reporting what the page actually looks like, not just that tests pass.

**3. Type consistency.** `seed.seed_example(conn)` (Task 1) is used by every test in Tasks 2 and 3. `create_app(db_path)` (Task 1) is extended, not replaced, by Tasks 2 and 3. `discover.pipeline_counts` (Task 3) is new and additive alongside the seven existing functions. The four JSON columns are parsed through one `_loads` helper defined in Task 1 and reused in Task 2.

**4. Pressure tests planted deliberately.** The Stage 3 lesson was that fixtures which only show the happy path produce code that looks right until real data arrives — the profiling-index-pages defect survived six review gates for exactly that reason. So:
- **The seed data is specified as a table of edge states**, not a list of brokers. Half the rows have NULLs somewhere.
- **`test_detail_never_prints_the_word_none`** iterates every seeded broker and fails if a raw `None` reaches the HTML. This is the assertion most likely to catch a real defect, because Jinja2 renders `None` as the string "None" without complaint.
- **`test_awaiting_profile_agrees_with_the_queue`** binds the dashboard's count to the actual queue predicate, so the two cannot drift.
- Task 1 step 4 asks explicitly whether the page *looks* broken even if it renders — a page showing "None" in six columns passes its tests and fails its purpose.

**5. Known weakness.** `create_app` opens a connection per request and never closes it, matching the CLI's existing style. Fine for a single-operator localhost tool; wrong if this ever serves more than one person, which is also when auth becomes mandatory. Both belong to the same future change.
