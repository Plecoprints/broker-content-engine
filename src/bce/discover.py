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


#: Warmest first (spec §4). Ordering only: every qualified broker is still
#: returned and still receives identical treatment — affinity decides position in
#: the queue and nothing else, which is what keeps §4 compatible with §2's ban on
#: tiered service. There is no filter or threshold reading this anywhere.
_AFFINITY_ORDER = (
    "CASE b.sunreef_affinity WHEN 'lists_inventory' THEN 0 "
    "WHEN 'mentions' THEN 1 ELSE 2 END, b.name"
)


def unprofiled_brokers(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Qualified brokers that have no voice profile yet (spec §5 Stage 3).

    Ordered warmest-first (spec §4): with a 50-broker cap and a 20-call limit,
    profiling order decides which brokers reach the review queue at all, and §13
    asks the pilot to run on a high-affinity broker. Alphabetical order made that
    a coin flip.
    """
    return conn.execute(
        "SELECT b.id, b.domain FROM broker b "
        "LEFT JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND v.broker_id IS NULL "
        f"ORDER BY {_AFFINITY_ORDER} LIMIT ?",
        (limit,),
    ).fetchall()


def undrafted_brokers(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    """Qualified, profiled brokers (a `voice_profile` row exists) with no
    draft yet (spec §5 Stage 4/5).

    A broker counts as drafted once any `draft` row exists for it — reached
    via `angle.broker_id`, since `draft` itself only carries `angle_id`.
    `drafting.draft_for_broker` never inserts an `angle` row without also
    inserting its long-form `draft` row in the same commit, so this is
    equivalent to "has an angle" in practice; phrased as `NOT EXISTS` over
    `draft` (rather than over `angle`) so it stays correct even if that
    invariant ever changes.

    `b.qualified = 1` is required explicitly: a profile row does not imply
    qualification stayed intact. `clear_qualification` sets `qualified=NULL`
    while leaving `voice_profile` alone, and without this filter a broker
    pulled from the working set via `bce requalify` would still be selected
    here and spend three Opus calls on someone deliberately rejected.

    Ordered warmest-first (spec §4), the same `_AFFINITY_ORDER` as
    `unprofiled_brokers`: with up to 50 qualified brokers and only 10 drafted
    per run, ordering doesn't just sequence, it selects, and §13 asks the
    pilot to run on a high-affinity broker. Ordering only -- every eligible
    broker is still returned and treated identically; affinity decides
    position in the queue and nothing else (see `_AFFINITY_ORDER`).
    """
    return conn.execute(
        "SELECT b.id, b.domain FROM broker b "
        "JOIN voice_profile v ON v.broker_id = b.id "
        "WHERE b.qualified = 1 AND NOT EXISTS ("
        "  SELECT 1 FROM draft d JOIN angle a ON a.id = d.angle_id "
        "  WHERE a.broker_id = b.id"
        ") "
        f"ORDER BY {_AFFINITY_ORDER} LIMIT ?",
        (limit,),
    ).fetchall()


def clear_drafts(conn: sqlite3.Connection, *, domain: str | None = None) -> int:
    """Send brokers back to Stage 4 by deleting their angle and draft rows.

    Without this, a broker whose long draft succeeded but whose short
    condensation failed (`drafting.draft_for_broker`'s `short_written=False`
    path) is stranded: `undrafted_brokers` excludes any broker with a `draft`
    row at all, so no command can ever select that broker again, and a
    newsletter-only broker is left with exactly the long-form artifact they
    cannot use (spec §5: "A broker with only a newsletter receives the short
    form as the primary deliverable").

    With a domain, that broker's `angle` and `draft` rows are cleared
    unconditionally -- whatever state they are in, deliberately re-spending
    the angle and long-draft calls is an explicit operator action (spec
    §11.5 treats retries as deliberate, never automatic).

    With no domain, only *degraded* brokers are cleared: those with a long
    draft but no matching short draft under the same angle. A fully-drafted
    broker is left alone, so a bulk `bce redraft` cannot silently re-spend
    calls on brokers that already succeeded.

    Returns the number of brokers cleared (not the number of rows deleted),
    mirroring `clear_qualification` / `clear_voice_profile`.
    """
    if domain is not None:
        target = normalize_domain(domain) or domain.strip().lower()
        broker = conn.execute(
            "SELECT id FROM broker WHERE domain=?", (target,)
        ).fetchone()
        broker_ids = [broker["id"]] if broker is not None else []
    else:
        rows = conn.execute(
            "SELECT DISTINCT a.broker_id FROM angle a "
            "JOIN draft d ON d.angle_id = a.id AND d.format = 'long' "
            "WHERE NOT EXISTS ("
            "  SELECT 1 FROM draft d2 WHERE d2.angle_id = a.id AND d2.format = 'short'"
            ")"
        ).fetchall()
        broker_ids = [r["broker_id"] for r in rows]

    cleared = 0
    for broker_id in broker_ids:
        angle_ids = [
            r["id"]
            for r in conn.execute("SELECT id FROM angle WHERE broker_id=?", (broker_id,))
        ]
        if not angle_ids:
            continue
        placeholders = ",".join("?" * len(angle_ids))
        conn.execute(f"DELETE FROM draft WHERE angle_id IN ({placeholders})", angle_ids)
        conn.execute(f"DELETE FROM angle WHERE id IN ({placeholders})", angle_ids)
        cleared += 1
    conn.commit()
    return cleared


def clear_voice_profile(
    conn: sqlite3.Connection, *, domain: str | None = None
) -> int:
    """Send brokers back to Stage 3 by deleting their voice profile row (I3).

    `unprofiled_brokers` selects on row *existence*, and `profile_broker` writes a
    row even when `classify` returned `{}` — an API error, a refusal, or an
    unparseable payload. Without this, a broker profiled during a transient
    outage keeps a row whose entire judgement half is NULL, and no command can
    ever reach the carefully-written upsert to repair it. Same shape as
    `clear_qualification` (spec §5 Stage 2's `requalify`, for the same reason).

    With no domain, only *degraded* rows are cleared — those with no `register`,
    which is the field the classifier is required to return. Good profiles are
    left alone so a bulk repair cannot burn the §11.5 call budget re-doing work.
    """
    if domain is not None:
        target = normalize_domain(domain) or domain.strip().lower()
        cursor = conn.execute(
            "DELETE FROM voice_profile WHERE broker_id IN "
            "(SELECT id FROM broker WHERE domain=?)",
            (target,),
        )
    else:
        cursor = conn.execute("DELETE FROM voice_profile WHERE register IS NULL")
    conn.commit()
    return cursor.rowcount
