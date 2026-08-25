"""Stage 1 — build the candidate shortlist (spec §5)."""
import csv
import io
import re
import sqlite3

_AFFINITY_RANK = {
    "lists_inventory": 0,
    "mentions": 1,
    "unknown": 2,
    "none": 3,
}

REQUIRED_COLUMNS = frozenset({"name", "domain"})

# A hostname: at least two dot-separated labels of letters/digits/hyphens.
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$"
)


class CsvHeaderError(ValueError):
    """The CSV has no usable `name`/`domain` header row.

    Carries the headers actually found so the operator is told what was wrong
    instead of seeing "imported 0 brokers", which is what a correct empty
    import also prints.
    """

    def __init__(self, found: list[str]):
        self.found = found
        super().__init__(
            "CSV must have 'name' and 'domain' columns; found: "
            + (", ".join(found) if found else "(no header row)")
        )


def normalize_domain(cell: str) -> str | None:
    """Canonical bare hostname from a CSV cell, or None if it is not one.

    Directory and CRM exports carry URLs rather than bare domains, and
    `https://acme.com/` interpolated into `https://{domain}/` yields an
    unfetchable URL that reads as an unreachable site. Normalising on import
    also keeps `acme.com` and `www.acme.com` from being two brokers against the
    spec §6 cap.
    """
    value = (cell or "").strip().lower()
    if not value:
        return None
    if "//" in value:
        value = value.split("//", 1)[1]
    for separator in ("/", "?", "#"):
        value = value.split(separator, 1)[0]
    value = value.rsplit("@", 1)[-1]          # drop any userinfo
    value = value.split(":", 1)[0]            # drop any port
    value = value.strip().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value if _HOSTNAME_RE.match(value) else None


def parse_rows(csv_text: str) -> tuple[list[dict], list[str]]:
    """Parse an import CSV into (usable rows, unusable domain cells).

    Headers are matched case-insensitively and whitespace/BOM-tolerantly:
    `Name,Domain` out of Excel or a CRM is an ordinary CSV, not an empty one.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    found = reader.fieldnames or []
    normalized = [
        (field or "").strip().lstrip("\ufeff").strip().lower() for field in found
    ]
    if not REQUIRED_COLUMNS <= set(normalized):
        raise CsvHeaderError(found)
    reader.fieldnames = normalized

    rows: list[dict] = []
    rejected: list[str] = []
    for raw in reader:
        name = (raw.get("name") or "").strip()
        cell = (raw.get("domain") or "").strip()
        if not name or not cell:
            continue
        domain = normalize_domain(cell)
        if domain is None:
            rejected.append(cell)
            continue
        rows.append({
            "name": name,
            "domain": domain,
            "region": (raw.get("region") or "").strip() or None,
        })
    return rows, rejected


def count_new_domains(conn: sqlite3.Connection, csv_text: str) -> int:
    """How many brokers this CSV would actually add (spec §6 cap input).

    The manual source is a master list the operator keeps appending to, so
    re-importing it must not be counted against the cap a second time.
    """
    rows, _ = parse_rows(csv_text)
    existing = {r["domain"] for r in conn.execute("SELECT domain FROM broker")}
    new: set[str] = set()
    for row in rows:
        if row["domain"] not in existing:
            new.add(row["domain"])
    return len(new)


def import_csv(conn: sqlite3.Connection, csv_text: str) -> int:
    rows, _ = parse_rows(csv_text)
    inserted = 0
    for row in rows:
        try:
            conn.execute(
                "INSERT INTO broker (name, domain, region, source) "
                "VALUES (?, ?, ?, 'manual')",
                (row["name"], row["domain"], row["region"]),
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


def clear_qualification(
    conn: sqlite3.Connection, *, domain: str | None = None
) -> int:
    """Send brokers back to Stage 2 by clearing their verdict.

    Without this a broker misjudged once — a bad URL cell, a transient outage,
    a WAF block — is rejected forever, because `unqualified_brokers` only ever
    looks at `qualified IS NULL`. With no domain, every *rejected* broker is
    cleared; qualified brokers are left alone.
    """
    reset = (
        "UPDATE broker SET qualified=NULL, qualified_reason=NULL, "
        "robots_allowed=NULL, has_editorial=NULL, has_newsletter=NULL, "
        "newsletter_evidence=NULL, editorial_last_post=NULL "
    )
    if domain is not None:
        target = normalize_domain(domain) or domain.strip().lower()
        cursor = conn.execute(reset + "WHERE domain=?", (target,))
    else:
        cursor = conn.execute(reset + "WHERE qualified=0")
    conn.commit()
    return cursor.rowcount


def unprofiled_brokers(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Qualified brokers that have no voice profile yet (spec §5 Stage 3)."""
    return conn.execute(
        "SELECT b.id, b.domain FROM broker b "
        "LEFT JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND v.broker_id IS NULL "
        "ORDER BY b.name LIMIT ?",
        (limit,),
    ).fetchall()
