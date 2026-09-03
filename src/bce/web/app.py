"""Operator UI (spec §9). Reads SQLite directly.

Hardened 2026-09-02 against findings 2-5 and 8 of the IT risk assessment.
The theme of all of them is the same: "localhost only, no auth" was a
*comment*, and a comment is not a control. `--host 0.0.0.0` would have put
the draft queue, the broker list and two unauthenticated POST endpoints on
the network. See `_guard` below and `cli.cmd_serve`.
"""
import base64
import binascii
import csv
import io
import json
import os
import secrets
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from bce import db, discover, keywords, originality
from bce.cli import MAX_BROKERS

#: Env var holding the operator password. Absent means "no auth", which
#: `cli.cmd_serve` permits only on a loopback bind.
PASSWORD_ENV = "BCE_OPERATOR_PASSWORD"

#: Upload ceiling for the CSV importer. `await file.read()` with no argument
#: read the whole body into memory, so any client could exhaust it. §6 caps
#: the system at 50 brokers, so a legitimate import is a few kilobytes; one
#: megabyte is generous by three orders of magnitude and still bounded.
MAX_UPLOAD_BYTES = 1_000_000

#: Fixed-window throttle on state-changing endpoints.
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 60

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _loads(value, default):
    """JSON columns may be NULL or malformed; never raise while rendering."""
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _redirect(path: str, message: str, *, ok: bool) -> RedirectResponse:
    """Carry the result across a redirect via a query parameter (§9: no session store).

    303 turns the browser's next request into a GET, so reloading the landing
    page never resubmits the form.
    """
    query = urlencode({"msg": message, "ok": "1" if ok else "0"})
    return RedirectResponse(url=f"{path}?{query}", status_code=303)


def _flash(request: Request) -> dict:
    return {
        "message": request.query_params.get("msg"),
        "ok": request.query_params.get("ok") == "1",
    }


def _paragraphs(body: str | None) -> list[str]:
    """Split markdown-ish prose into paragraphs on blank lines.

    Draft bodies are prose, not real markdown (see `bce.drafting`), so this
    deliberately does not pull in a markdown renderer -- it only preserves
    the paragraph breaks the model actually wrote, one `<p>` per blank-line-
    separated block. `None` degrades to no paragraphs, never a rendered
    "None".
    """
    if not body:
        return []
    return [p.strip() for p in body.split("\n\n") if p.strip()]


def _keywords_for_draft(conn, draft) -> dict:
    """The primary/secondary keyword selection actually baked into `draft`
    (a `sqlite3.Row` or None), read back from `draft_keyword` joined to
    `keyword` -- the same `{"primary": row_or_None, "secondary": [rows]}`
    shape `bce.keywords.select_for_draft` returns, so the keyword panel
    partial (`_keyword_panel.html`) works from one shape regardless of
    whether it is fed a fresh selection or, as here, a persisted one.

    A draft with no row at all (condensation failed, or no draft yet) has no
    keywords to show -- returns the same empty shape `select_for_draft`
    returns when nothing qualified, so the panel's "no keyword" branch reads
    identically either way.
    """
    if draft is None:
        return {"primary": None, "secondary": []}
    rows = conn.execute(
        "SELECT k.*, dk.role FROM draft_keyword dk "
        "JOIN keyword k ON k.id = dk.keyword_id "
        "WHERE dk.draft_id=?",
        (draft["id"],),
    ).fetchall()
    primary = next((dict(r) for r in rows if r["role"] == "primary"), None)
    secondary = [dict(r) for r in rows if r["role"] == "secondary"]
    return {"primary": primary, "secondary": secondary}


def _broker_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"]


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _authorized(request: Request, password: str) -> bool:
    """HTTP Basic, compared in constant time. Username is ignored -- there is
    one operator (§9) and inventing a second secret to remember would make
    the control likelier to be turned off than to be used."""
    header = request.headers.get("authorization", "")
    scheme, _, encoded = header.partition(" ")
    if scheme.lower() != "basic" or not encoded:
        return False
    try:
        decoded = base64.b64decode(encoded).decode("utf-8", errors="replace")
    except (ValueError, binascii.Error):
        return False
    _, _, supplied = decoded.partition(":")
    return secrets.compare_digest(supplied, password)


def _within_rate_limit(hits: deque) -> bool:
    """Fixed window across all clients, not per-IP: this binds to loopback by
    default and the threat is an accidental or hostile flood of the whole
    endpoint, not one noisy client among many legitimate ones."""
    now = time.monotonic()
    while hits and now - hits[0] > RATE_LIMIT_WINDOW_SECONDS:
        hits.popleft()
    if len(hits) >= RATE_LIMIT_REQUESTS:
        return False
    hits.append(now)
    return True


def _csrf_ok(request: Request, expected: str) -> bool:
    """Token from the `csrf` query parameter or the `X-CSRF-Token` header.

    The query parameter, rather than a hidden form field, is a deliberate
    trade. Checking a body field in middleware means consuming the request
    body and re-injecting it so the route can read it again -- workable for
    urlencoded, fiddly and fragile for the multipart upload. Putting the token
    in the form's `action` keeps the check body-free and therefore reliable
    for both endpoints.

    The cost is that the token appears in the URL, so it reaches server logs
    and browser history. That is acceptable here and would not be elsewhere:
    the token authorises nothing on its own, it is per-process and dies with
    the server, and this binds to loopback with no cross-origin reader. What
    it must do is be unguessable by a page on another origin, and a value in
    our own form's action is exactly as unreachable to that page as a hidden
    input would be.
    """
    for supplied in (
        request.headers.get("x-csrf-token", ""),
        request.query_params.get("csrf", ""),
    ):
        if supplied and secrets.compare_digest(supplied, expected):
            return True
    return False


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Broker Content Engine")
    app.state.db_path = db_path
    # Per-process, not per-session: this is a single-operator tool with no
    # session store (§9). An attacker's page cannot read this token, which is
    # all a CSRF defence needs to do; rotating it per session would add a
    # store for no gain.
    app.state.csrf_token = secrets.token_urlsafe(32)
    app.state.password = os.environ.get(PASSWORD_ENV) or None
    app.state.hits = deque()
    _TEMPLATES.env.filters["fromjson"] = lambda v: _loads(v, None)
    _TEMPLATES.env.filters["paragraphs"] = _paragraphs
    _TEMPLATES.env.globals["csrf_token"] = lambda: app.state.csrf_token

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        """Auth, throttle and CSRF, in that order, ahead of every route.

        Middleware rather than per-route dependencies so a future route
        cannot be added without them -- the failure mode being fixed here is
        precisely a control that was assumed rather than applied.
        """
        password = app.state.password
        if password is not None and not _authorized(request, password):
            return Response(
                "Authentication required.", status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Broker Content Engine"'},
            )
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            if not _within_rate_limit(app.state.hits):
                return Response("Too many requests.", status_code=429)
            if not _csrf_ok(request, app.state.csrf_token):
                return Response(
                    "CSRF token missing or invalid. Reload the page and retry.",
                    status_code=403,
                )
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def shortlist(request: Request):
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)
        brokers = discover.list_brokers(conn)
        return _TEMPLATES.TemplateResponse(
            request=request, name="shortlist.html",
            context={
                "brokers": brokers,
                "broker_ids_with_drafts": discover.broker_ids_with_drafts(conn),
                **_flash(request),
            },
        )

    @app.get("/broker/{broker_id}/drafts", response_class=HTMLResponse)
    def broker_drafts(request: Request, broker_id: int):
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)
        broker = conn.execute(
            "SELECT * FROM broker WHERE id=?", (broker_id,)
        ).fetchone()
        if broker is None:
            raise HTTPException(status_code=404, detail="broker not found")

        # Only the chosen angle is ever persisted (spec §5 Stage 4) -- take
        # the most recent in case a broker was ever redrafted more than once.
        angle = conn.execute(
            "SELECT * FROM angle WHERE broker_id=? ORDER BY id DESC LIMIT 1",
            (broker_id,),
        ).fetchone()

        long_draft = medium_draft = short_draft = None
        if angle is not None:
            long_draft = conn.execute(
                "SELECT * FROM draft WHERE angle_id=? AND format='long' "
                "ORDER BY id DESC LIMIT 1",
                (angle["id"],),
            ).fetchone()
            medium_draft = conn.execute(
                "SELECT * FROM draft WHERE angle_id=? AND format='medium' "
                "ORDER BY id DESC LIMIT 1",
                (angle["id"],),
            ).fetchone()
            short_draft = conn.execute(
                "SELECT * FROM draft WHERE angle_id=? AND format='short' "
                "ORDER BY id DESC LIMIT 1",
                (angle["id"],),
            ).fetchone()

        return _TEMPLATES.TemplateResponse(
            request=request, name="draft_viewer.html",
            context={
                "broker": broker,
                "angle": angle,
                "long_draft": long_draft,
                "medium_draft": medium_draft,
                "short_draft": short_draft,
                "long_keywords": _keywords_for_draft(conn, long_draft),
                "medium_keywords": _keywords_for_draft(conn, medium_draft),
                "short_keywords": _keywords_for_draft(conn, short_draft),
                "max_difficulty": keywords.MAX_DIFFICULTY,
                "min_volume": keywords.MIN_VOLUME,
                "uniqueness_threshold": originality.UNIQUENESS_THRESHOLD,
                **_flash(request),
            },
        )

    @app.get("/add", response_class=HTMLResponse)
    def add_form(request: Request):
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)
        return _TEMPLATES.TemplateResponse(
            request=request, name="add.html",
            context={
                "existing": _broker_count(conn),
                "max_brokers": MAX_BROKERS,
                **_flash(request),
            },
        )

    @app.post("/add/csv")
    async def add_csv(file: UploadFile = File(...)):
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)
        # Bounded read. `await file.read()` with no argument pulled the whole
        # body into memory, which is a one-line denial of service. Reading one
        # byte past the cap is how we tell "exactly at the limit" from "over
        # it" without buffering the overage.
        raw = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(raw) > MAX_UPLOAD_BYTES:
            return _redirect(
                "/add",
                f"That file is larger than {MAX_UPLOAD_BYTES // 1000} kB. A "
                f"broker list for the {MAX_BROKERS}-broker cap is a few "
                "kilobytes — check you picked the right file.",
                ok=False,
            )
        # utf-8-sig: Excel's "CSV UTF-8" writes a BOM (same handling as `bce
        # import`'s file read — see cli.cmd_import).
        text = raw.decode("utf-8-sig", errors="replace")

        try:
            rows, rejected = discover.parse_rows(text)
        except discover.CsvHeaderError as exc:
            found = ", ".join(exc.found) if exc.found else "(no header row)"
            return _redirect(
                "/add",
                f"That CSV's headers were not recognized — found: {found}. "
                "Expected columns named 'name' and 'domain'.",
                ok=False,
            )

        existing = _broker_count(conn)
        # Only brokers this import would actually add count against the cap
        # (spec §6): re-importing a growing master list must not double-count.
        incoming = discover.count_new_domains(conn, text)
        if existing + incoming > MAX_BROKERS:
            return _redirect(
                "/add",
                f"Refused: {existing} existing + {incoming} new would exceed "
                f"the {MAX_BROKERS}-broker cap (spec section 6). Trim the CSV "
                "and try again.",
                ok=False,
            )

        inserted = discover.import_csv(conn, text)
        duplicates = len(rows) - inserted
        message = f"Imported {_plural(inserted, 'broker')}"
        details = []
        if duplicates:
            details.append(f"{_plural(duplicates, 'duplicate')} skipped")
        if rejected:
            details.append(f"{_plural(len(rejected), 'invalid domain')} skipped")
        if details:
            message += f" ({', '.join(details)})"
        return _redirect("/", message, ok=True)

    @app.post("/add/manual")
    def add_manual(name: str = Form(""), domain: str = Form(""), region: str = Form("")):
        # Defaults, not Form(...): an empty-valued urlencoded field is not
        # reliably re-emitted by the form parser, which would otherwise turn a
        # blank field into a 422 before our own "name is required" /
        # normalize_domain checks below ever run.
        conn = db.connect(app.state.db_path)
        db.init_schema(conn)

        clean_name = name.strip()
        if not clean_name:
            return _redirect("/add", "Name is required.", ok=False)
        normalized = discover.normalize_domain(domain)
        if normalized is None:
            return _redirect(
                "/add",
                f"'{domain}' is not a hostname — expected something like "
                "acme.com, not a URL or free text.",
                ok=False,
            )

        # Reuse the exact CSV pipeline (normalization, cap check, dedup,
        # insert) for a single synthetic row instead of a second insert path.
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["name", "domain", "region"])
        writer.writerow([clean_name, normalized, region.strip()])
        csv_text = buf.getvalue()

        existing = _broker_count(conn)
        incoming = discover.count_new_domains(conn, csv_text)
        if existing + incoming > MAX_BROKERS:
            return _redirect(
                "/add",
                f"Refused: adding this broker would exceed the {MAX_BROKERS}"
                f"-broker cap (spec section 6) — currently {existing}.",
                ok=False,
            )

        inserted = discover.import_csv(conn, csv_text)
        if inserted == 0:
            return _redirect(
                "/", f"'{normalized}' is already in the broker list — nothing added.",
                ok=True,
            )
        return _redirect("/", f"Added {clean_name} ({normalized}).", ok=True)

    return app
