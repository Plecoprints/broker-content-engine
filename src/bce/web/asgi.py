"""ASGI entrypoint for running the operator UI + broker portal under a process
manager (supervisor/uvicorn) instead of `bce serve`.

`bce serve` is the loopback-only CLI path with its "no non-loopback bind
without a password" guard (spec §9). This module is the preview-environment
counterpart: it exposes the same app on the port the platform preview proxies
(3000), so the UI is viewable in the browser. The DB path comes from
BCE_DB_PATH so the process manager, not code, decides which database is served.
"""
import os

from bce.web.app import create_app

app = create_app(os.environ.get("BCE_DB_PATH", "/app/bce.db"))
