"""CLI entry point. Enforces the spec §6 volume cap."""
import argparse
import sys
from pathlib import Path

from bce import db, discover, drafting, keywords, profile, qualify, seed
from bce.angles import AngleClient
from bce.draft import DraftClient
from bce.fetch import Fetcher
from bce.llm import ProfileClient

MAX_BROKERS = 50
DEFAULT_QUALIFY_LIMIT = 20
MAX_PROFILE_CALLS = 20
#: Each broker drafted costs four Claude calls (angles, long, medium, short —
#: spec v0.6 §5 added the medium format) — see `drafting.draft_for_broker`.
#: The ceiling below counts brokers, not calls, which is why the refusal
#: message spells that out (spec §11.5).
#:
#: Kept at roughly the same total-call budget as before rather than silently
#: tripling it alongside the third format: the previous ceiling of 10 brokers
#: at 3 calls/broker was a 30-call session budget. At 4 calls/broker that same
#: budget is 30 // 4 = 7 brokers, so the ceiling actually drops with the
#: fourth call rather than merely growing more slowly.
MAX_DRAFT_CALLS = 7


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


def cmd_keywords(db_path: str, csv_path: str) -> int:
    """Load a Semrush keyword export into the `keyword` table (spec §5b).

    Mirrors `cmd_import`'s error handling: a missing file or an unusable
    header is reported and refused (rc=1), not a silent zero-row import. On
    success, prints the qualify/non-qualify split and the threshold each
    failure missed -- "that report is the feature" (spec change brief) -- and
    every skipped, unparseable row and why, never silently dropped.
    """
    conn = db.connect(db_path)
    db.init_schema(conn)
    try:
        result = keywords.load_bank(conn, csv_path)
    except FileNotFoundError:
        print(f"error: CSV file not found: {csv_path}")
        return 1
    except keywords.NoPhraseColumnError as exc:
        print(f"error: {exc}")
        return 1

    split = f"{result.qualifying} qualify, {result.non_qualifying} do not"
    if result.non_qualifying:
        split += (
            f" ({result.missed_difficulty} missed on difficulty, "
            f"{result.missed_volume} missed on volume)"
        )
    print(f"loaded {result.imported} keywords from {csv_path} ({split})")

    print(
        f"segment relevance: {result.segment_relevant} relevant, "
        f"{result.segment_excluded} excluded"
    )
    for reason, count in sorted(result.excluded_by_reason.items()):
        volume = result.excluded_volume_by_reason.get(reason, 0)
        print(f"  excluded ({reason}): {count} keyword(s), {volume} monthly volume")

    print(
        f"editorial intent: {result.editorial} editorial, "
        f"{result.non_editorial} not editorial (commercial retained; "
        f"transactional/navigational/unknown excluded)"
    )

    for reason in result.skipped:
        print(f"warning: skipped {reason}")
    if result.skipped:
        print(f"skipped {len(result.skipped)} unparseable row(s) — see warnings above")
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


def _channel_label(value: int | None) -> str:
    """yes/no/? for a tri-state has_editorial/has_newsletter column (A3).

    `None` means Stage 2 never looked (unreachable/disallowed homepage), which
    is distinct from having looked and found nothing.
    """
    if value is None:
        return "?"
    return "yes" if value else "no"


def cmd_list(db_path: str) -> int:
    """Print one line per broker (spec §4: every broker `list_brokers`
    returns must print — no filtering, grouping, or tiering by affinity).

    Alongside the existing name/domain/affinity/state columns, this also
    surfaces which publishing channels were found and the editorial date (or
    `unknown`/`-`), so an operator can tell "no channel" apart from "we could
    not date the channel" (Residual A3) instead of `editorial_last_post`
    being written and read by nothing.
    """
    conn = db.connect(db_path)
    for row in discover.list_brokers(conn):
        state = {1: "qualified", 0: "rejected"}.get(row["qualified"], "pending")
        editorial = _channel_label(row["has_editorial"])
        newsletter = _channel_label(row["has_newsletter"])
        last_post = row["editorial_last_post"] or "-"
        print(
            f"{row['name']:<30} {row['domain']:<28} {row['sunreef_affinity']:<16} "
            f"{state:<10} editorial={editorial:<3} last_post={last_post:<10} "
            f"newsletter={newsletter}"
        )
    return 0


def cmd_profile(db_path: str, limit: int = MAX_PROFILE_CALLS) -> int:
    # Both sides, because SQLite treats a negative LIMIT as *unbounded*: an
    # upper-bound-only guard let `--limit -1` profile every qualified broker (up
    # to the §6 cap of 50) against a 20-call ceiling. A limit below 1 is also
    # simply not a request to do any work.
    if limit < 1 or limit > MAX_PROFILE_CALLS:
        print(
            f"refused: {limit} is outside the 1-{MAX_PROFILE_CALLS} call ceiling "
            f"(spec section 11.5). Raise it deliberately or correct --limit."
        )
        return 1
    conn = db.connect(db_path)
    db.init_schema(conn)
    rows = discover.unprofiled_brokers(conn, limit)
    if not rows:
        print("no qualified brokers awaiting a profile")
        return 0
    fetcher = Fetcher()
    profile_client = ProfileClient()
    for row in rows:
        result = profile.profile_broker(conn, row["id"], fetcher, profile_client)
        print(f"{row['domain']}: {_profile_label(result)}")
    return 0


def _profile_label(result) -> str:
    """What actually happened, including silent degradation (I5).

    A row written with every judgement field NULL — the Claude call errored,
    refused, or returned something unparseable — used to print `profiled`. It is
    both wrong and, until `bce reprofile`, unrepairable, so it must not read as
    success.
    """
    if not result:
        return "no articles found"
    if not result.classified:
        return "profiled (statistics only — classification failed)"
    return "profiled"


def cmd_reprofile(db_path: str, domain: str | None = None) -> int:
    """Clear a stored voice profile so Stage 3 looks again (I3).

    `unprofiled_brokers` selects on row existence, so a broker profiled during an
    API outage keeps a statistics-only row forever. Mirrors `requalify`.
    """
    conn = db.connect(db_path)
    db.init_schema(conn)
    cleared = discover.clear_voice_profile(conn, domain=domain)
    if cleared == 0:
        if domain:
            print(f"no voice profile found for {domain}")
            return 1
        print("no degraded voice profiles to reprofile")
        return 0
    scope = domain if domain else "degraded profiles"
    print(f"cleared {cleared} voice profile(s) for {scope}; run `bce profile` again")
    return 0


def cmd_draft(db_path: str, limit: int = MAX_DRAFT_CALLS) -> int:
    # Both sides, and checked before any client is constructed: SQLite treats
    # a negative LIMIT as *unbounded*, and an upper-bound-only guard on
    # `cmd_profile` let `--limit -1` bypass its ceiling entirely before a
    # whole-branch review caught it (spec §11.5, same class of bug here).
    if limit < 1 or limit > MAX_DRAFT_CALLS:
        print(
            f"refused: {limit} is outside the 1-{MAX_DRAFT_CALLS} broker ceiling "
            f"(spec section 11.5). Each broker drafted costs four API calls "
            f"(angles, long draft, medium draft, short draft) -- this ceiling "
            f"counts brokers, not calls. Raise it deliberately or correct --limit."
        )
        return 1
    conn = db.connect(db_path)
    db.init_schema(conn)
    rows = discover.undrafted_brokers(conn, limit)
    if not rows:
        print("no profiled brokers awaiting a draft")
        return 0
    angle_client = AngleClient()
    draft_client = DraftClient()
    for row in rows:
        result = drafting.draft_for_broker(conn, row["id"], angle_client, draft_client)
        print(f"{row['domain']}: {_draft_label(result)}")
    return 0


def _draft_label(result) -> str:
    """What actually happened, including partial-condensation-failed cases.

    Mirrors `_profile_label`: a caller must be able to tell "all three
    formats written" from "long draft kept, medium and/or short condensation
    failed" rather than both printing an unqualified "drafted".
    """
    if not result:
        return "no draft written"
    failed = [
        name
        for name, ok in (("medium", result.medium_written), ("short", result.short_written))
        if not ok
    ]
    if failed:
        return f"long draft written ({' and '.join(failed)} condensation failed)"
    return "drafted (long + medium + short)"


def cmd_redraft(db_path: str, domain: str | None = None) -> int:
    """Clear a broker's angle+draft rows so Stage 4 drafts again (F1).

    Without this, a broker whose long draft succeeded but whose short
    condensation failed is stranded forever: `undrafted_brokers` excludes any
    broker with a `draft` row at all. Mirrors `reprofile` / `requalify`.
    """
    conn = db.connect(db_path)
    db.init_schema(conn)
    cleared = discover.clear_drafts(conn, domain=domain)
    if cleared == 0:
        if domain:
            print(f"no draft found for {domain}")
            return 1
        print("no degraded drafts to redraft")
        return 0
    scope = domain if domain else "degraded drafts"
    print(f"cleared {cleared} draft(s) for {scope}; run `bce draft` again")
    return 0


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bce")
    parser.add_argument("--db", default="bce.db")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init")
    p_import = sub.add_parser("import")
    p_import.add_argument("csv")
    p_keywords = sub.add_parser("keywords")
    p_keywords.add_argument("csv")
    p_qualify = sub.add_parser("qualify")
    p_qualify.add_argument("--limit", type=int, default=DEFAULT_QUALIFY_LIMIT)
    p_requalify = sub.add_parser("requalify")
    p_requalify.add_argument(
        "domain", nargs="?",
        help="broker domain to requalify; omit to clear every rejected broker",
    )
    sub.add_parser("list")
    p_profile = sub.add_parser("profile")
    p_profile.add_argument("--limit", type=int, default=MAX_PROFILE_CALLS)
    p_reprofile = sub.add_parser("reprofile")
    p_reprofile.add_argument(
        "domain", nargs="?",
        help="broker domain to reprofile; omit to clear every degraded profile",
    )
    p_draft = sub.add_parser("draft")
    p_draft.add_argument("--limit", type=int, default=MAX_DRAFT_CALLS)
    p_redraft = sub.add_parser("redraft")
    p_redraft.add_argument(
        "domain", nargs="?",
        help="broker domain to redraft; omit to clear every degraded draft "
             "(long written, short condensation failed)",
    )
    sub.add_parser("seed-example")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.command == "init":
        return cmd_init(args.db)
    if args.command == "import":
        return cmd_import(args.db, args.csv)
    if args.command == "keywords":
        return cmd_keywords(args.db, args.csv)
    if args.command == "qualify":
        return cmd_qualify(args.db, args.limit)
    if args.command == "requalify":
        return cmd_requalify(args.db, args.domain)
    if args.command == "list":
        return cmd_list(args.db)
    if args.command == "profile":
        return cmd_profile(args.db, args.limit)
    if args.command == "reprofile":
        return cmd_reprofile(args.db, args.domain)
    if args.command == "draft":
        return cmd_draft(args.db, args.limit)
    if args.command == "redraft":
        return cmd_redraft(args.db, args.domain)
    if args.command == "seed-example":
        return cmd_seed_example(args.db)
    if args.command == "serve":
        return cmd_serve(args.db, args.host, args.port)
    print("unknown command", file=sys.stderr)
    return 2
