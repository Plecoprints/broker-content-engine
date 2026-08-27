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
