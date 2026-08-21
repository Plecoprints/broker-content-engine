"""Stage 1 — build the candidate shortlist (spec §5)."""
import csv
import io
import sqlite3

_AFFINITY_RANK = {
    "lists_inventory": 0,
    "mentions": 1,
    "unknown": 2,
    "none": 3,
}


def import_csv(conn: sqlite3.Connection, csv_text: str) -> int:
    reader = csv.DictReader(io.StringIO(csv_text))
    inserted = 0
    for row in reader:
        name = (row.get("name") or "").strip()
        domain = (row.get("domain") or "").strip()
        if not name or not domain:
            continue
        region = (row.get("region") or "").strip() or None
        try:
            conn.execute(
                "INSERT INTO broker (name, domain, region, source) "
                "VALUES (?, ?, ?, 'manual')",
                (name, domain, region),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            continue
    conn.commit()
    return inserted


def list_brokers(
    conn: sqlite3.Connection, *, qualified: bool | None = None
) -> list[sqlite3.Row]:
    sql = "SELECT * FROM broker"
    params: tuple = ()
    if qualified is not None:
        sql += " WHERE qualified = ?"
        params = (1 if qualified else 0,)
    rows = conn.execute(sql, params).fetchall()
    return sorted(
        rows,
        key=lambda r: (_AFFINITY_RANK.get(r["sunreef_affinity"], 2), r["name"]),
    )


def unqualified_brokers(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Brokers that have not yet been through Stage 2 qualification."""
    return conn.execute(
        "SELECT id, domain FROM broker WHERE qualified IS NULL LIMIT ?", (limit,)
    ).fetchall()
