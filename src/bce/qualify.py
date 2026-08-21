"""Stage 2 — qualification orchestrator (spec §5).

Composes the pure detectors from `bce.detectors` into a single verdict per
broker and persists it. No fetching or parsing logic of its own.

Affinity is recorded here but never influences the verdict (spec §4) — a
newsletter or editorial section are both qualifying publishing channels in
their own right (spec §4 v0.5); neither is required if the other is present.
"""
import sqlite3

from bce.detectors import (
    detect_max_length_ft,
    detect_newsletter,
    detect_sunreef_affinity,
    find_editorial_urls,
)

MIN_LENGTH_FT = 60


def _tri(value):
    """Preserve None ("never looked") instead of collapsing it to 0."""
    return None if value is None else (1 if value else 0)


def _save(conn, broker_id, *, qualified, reason, robots_allowed,
          affinity, evidence, segment_evidence, has_editorial,
          has_newsletter, newsletter_evidence):
    conn.execute(
        "UPDATE broker SET qualified=?, qualified_reason=?, robots_allowed=?, "
        "sunreef_affinity=?, affinity_evidence=?, segment_evidence=?, "
        "has_editorial=?, has_newsletter=?, newsletter_evidence=? WHERE id=?",
        (
            1 if qualified else 0, reason, 1 if robots_allowed else 0,
            affinity, evidence, segment_evidence,
            _tri(has_editorial), _tri(has_newsletter),
            newsletter_evidence, broker_id,
        ),
    )
    conn.commit()
    return {"qualified": qualified, "reason": reason}


def qualify_broker(conn: sqlite3.Connection, broker_id: int, fetcher) -> dict:
    row = conn.execute(
        "SELECT domain FROM broker WHERE id=?", (broker_id,)
    ).fetchone()
    url = f"https://{row['domain']}/"

    html = fetcher.get(url)
    if html is None:
        return _save(
            conn, broker_id, qualified=False, reason="unreachable_or_disallowed",
            robots_allowed=fetcher.robots_allows(url), affinity="unknown",
            evidence=None, segment_evidence=None, has_editorial=None,
            has_newsletter=None, newsletter_evidence=None,
        )

    affinity, evidence = detect_sunreef_affinity(html)
    length_ft = detect_max_length_ft(html)
    segment_evidence = f"max_detected_length_ft={length_ft}" if length_ft else None
    editorial_urls = find_editorial_urls(html, url)
    has_editorial = bool(editorial_urls)
    has_newsletter, newsletter_evidence = detect_newsletter(html)

    if length_ft is None or length_ft < MIN_LENGTH_FT:
        return _save(
            conn, broker_id, qualified=False, reason="below_length_threshold",
            robots_allowed=True, affinity=affinity, evidence=evidence,
            segment_evidence=segment_evidence, has_editorial=has_editorial,
            has_newsletter=has_newsletter, newsletter_evidence=newsletter_evidence,
        )

    if not has_editorial and not has_newsletter:
        return _save(
            conn, broker_id, qualified=False, reason="no_publishing_channel",
            robots_allowed=True, affinity=affinity, evidence=evidence,
            segment_evidence=segment_evidence, has_editorial=has_editorial,
            has_newsletter=has_newsletter, newsletter_evidence=newsletter_evidence,
        )

    return _save(
        conn, broker_id, qualified=True, reason="passed",
        robots_allowed=True, affinity=affinity, evidence=evidence,
        segment_evidence=segment_evidence, has_editorial=has_editorial,
        has_newsletter=has_newsletter, newsletter_evidence=newsletter_evidence,
    )
