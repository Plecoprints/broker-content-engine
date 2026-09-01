"""Operator UI (spec §9). Localhost only, no auth, reads SQLite directly."""
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from bce import db, discover, keywords
from bce.cli import MAX_BROKERS

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


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="Broker Content Engine")
    app.state.db_path = db_path
    _TEMPLATES.env.filters["fromjson"] = lambda v: _loads(v, None)
    _TEMPLATES.env.filters["paragraphs"] = _paragraphs

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
        raw = await file.read()
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
