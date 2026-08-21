"""CLI entry point. Enforces the spec §6 volume cap."""
import argparse
import sys
from pathlib import Path

from bce import db, discover, qualify
from bce.fetch import Fetcher

MAX_BROKERS = 50
DEFAULT_QUALIFY_LIMIT = 20


def cmd_init(db_path: str) -> int:
    conn = db.connect(db_path)
    db.init_schema(conn)
    print(f"initialized {db_path}")
    return 0


def cmd_import(db_path: str, csv_path: str) -> int:
    conn = db.connect(db_path)
    db.init_schema(conn)
    existing = conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"]
    text = Path(csv_path).read_text()
    incoming = max(0, len(text.strip().splitlines()) - 1)
    if existing + incoming > MAX_BROKERS:
        print(
            f"refused: {existing}+{incoming} exceeds the {MAX_BROKERS}-broker cap "
            f"(spec section 6). Trim the CSV or raise the cap deliberately."
        )
        return 1
    print(f"imported {discover.import_csv(conn, text)} brokers")
    return 0


def cmd_qualify(db_path: str, limit: int = DEFAULT_QUALIFY_LIMIT) -> int:
    conn = db.connect(db_path)
    fetcher = Fetcher()
    rows = conn.execute(
        "SELECT id, domain FROM broker WHERE qualified IS NULL LIMIT ?", (limit,)
    ).fetchall()
    for row in rows:
        verdict = qualify.qualify_broker(conn, row["id"], fetcher)
        print(f"{row['domain']}: {verdict['reason']}")
    return 0


def cmd_list(db_path: str) -> int:
    conn = db.connect(db_path)
    for row in discover.list_brokers(conn):
        state = {1: "qualified", 0: "rejected"}.get(row["qualified"], "pending")
        print(f"{row['name']:<30} {row['domain']:<28} {row['sunreef_affinity']:<16} {state}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bce")
    parser.add_argument("--db", default="bce.db")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    p_import = sub.add_parser("import")
    p_import.add_argument("csv")
    p_qualify = sub.add_parser("qualify")
    p_qualify.add_argument("--limit", type=int, default=DEFAULT_QUALIFY_LIMIT)
    sub.add_parser("list")

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args.db)
    if args.command == "import":
        return cmd_import(args.db, args.csv)
    if args.command == "qualify":
        return cmd_qualify(args.db, args.limit)
    if args.command == "list":
        return cmd_list(args.db)
    print("unknown command", file=sys.stderr)
    return 2
