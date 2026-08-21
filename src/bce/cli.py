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
    try:
        # utf-8-sig: Excel's "CSV UTF-8" writes a BOM, which would otherwise
        # become part of the first header name.
        text = Path(csv_path).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        print(f"error: CSV file not found: {csv_path}")
        return 1

    conn = db.connect(db_path)
    db.init_schema(conn)

    try:
        _, unusable = discover.parse_rows(text)
    except discover.CsvHeaderError as exc:
        print(f"error: {exc}")
        return 1

    for cell in unusable:
        print(
            f"warning: skipped {cell!r} — the domain column wants a hostname "
            f"like acme.com"
        )

    existing = conn.execute("SELECT COUNT(*) AS c FROM broker").fetchone()["c"]
    # Only brokers this import would actually add count against the cap: the
    # manual master list gets re-imported as it grows (spec §5 Stage 1).
    incoming = discover.count_new_domains(conn, text)
    if existing + incoming > MAX_BROKERS:
        print(
            f"refused: {existing}+{incoming} new exceeds the {MAX_BROKERS}-broker "
            f"cap (spec section 6). Trim the CSV or raise the cap deliberately."
        )
        return 1
    print(f"imported {discover.import_csv(conn, text)} brokers")
    return 0


def cmd_qualify(db_path: str, limit: int = DEFAULT_QUALIFY_LIMIT) -> int:
    conn = db.connect(db_path)
    # Upgrade an older file before reading columns it may not have yet (I2):
    # this is the command that used to die with "no such column: has_editorial".
    db.init_schema(conn)
    fetcher = Fetcher()
    rows = discover.unqualified_brokers(conn, limit)
    for row in rows:
        verdict = qualify.qualify_broker(conn, row["id"], fetcher)
        print(f"{row['domain']}: {verdict['reason']}")
    return 0


def cmd_requalify(db_path: str, domain: str | None = None) -> int:
    """Clear a stored verdict so Stage 2 looks again (I5).

    A broker rejected on a bad URL cell, a transient outage, or a WAF block is
    otherwise rejected forever.
    """
    conn = db.connect(db_path)
    db.init_schema(conn)
    cleared = discover.clear_qualification(conn, domain=domain)
    if cleared == 0:
        if domain:
            print(f"no broker found for {domain}")
            return 1
        print("no rejected brokers to requalify")
        return 0
    scope = domain if domain else "rejected brokers"
    print(f"cleared {cleared} verdict(s) for {scope}; run `bce qualify` again")
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
    p_requalify = sub.add_parser("requalify")
    p_requalify.add_argument(
        "domain", nargs="?",
        help="broker domain to requalify; omit to clear every rejected broker",
    )
    sub.add_parser("list")

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args.db)
    if args.command == "import":
        return cmd_import(args.db, args.csv)
    if args.command == "qualify":
        return cmd_qualify(args.db, args.limit)
    if args.command == "requalify":
        return cmd_requalify(args.db, args.domain)
    if args.command == "list":
        return cmd_list(args.db)
    print("unknown command", file=sys.stderr)
    return 2
