"""Stage 2 — qualification orchestrator (spec §5).

Composes the pure detectors from `bce.detectors` into a single verdict per
broker and persists it. No fetching or parsing logic of its own.

Affinity is recorded here but never influences the verdict (spec §4) — a
newsletter or editorial section are both qualifying publishing channels in
their own right (spec §4 v0.5); neither is required if the other is present.

Each detector is handed the input shape it was written for: extracted prose for
the length and affinity detectors, raw markup for the link/attribute ones.
"""
import sqlite3
from datetime import date

from bce.detectors import (
    detect_last_post_date,
    detect_max_length_ft,
    detect_newsletter,
    detect_sunreef_affinity,
    find_editorial_urls,
    visible_text,
)

MIN_LENGTH_FT = 60
#: Spec §4 — an editorial section counts only if updated in the last 12 months.
EDITORIAL_MAX_AGE_DAYS = 365
#: Recorded in `broker.editorial_last_post` when editorial links were found but
#: no publication date could be established. Deliberately not treated as fresh.
EDITORIAL_DATE_UNKNOWN = "unknown"


def _tri(value):
    """Preserve None ("never looked") instead of collapsing it to 0."""
    return None if value is None else (1 if value else 0)


def _save(conn, broker_id, *, qualified, reason, robots_allowed,
          affinity, evidence, segment_evidence, has_editorial,
          has_newsletter, newsletter_evidence, editorial_last_post=None):
    conn.execute(
        "UPDATE broker SET qualified=?, qualified_reason=?, robots_allowed=?, "
        "sunreef_affinity=?, affinity_evidence=?, segment_evidence=?, "
        "has_editorial=?, has_newsletter=?, newsletter_evidence=?, "
        "editorial_last_post=? WHERE id=?",
        (
            1 if qualified else 0, reason, 1 if robots_allowed else 0,
            affinity, evidence, segment_evidence,
            _tri(has_editorial), _tri(has_newsletter),
            newsletter_evidence, editorial_last_post, broker_id,
        ),
    )
    conn.commit()
    return {"qualified": qualified, "reason": reason}


def _editorial_recency(fetcher, editorial_urls, *, today=None):
    """(fresh_editorial_channel, recorded_last_post) for spec §4's 12 months.

    A link to a journal proves a link, not a publication, so the first editorial
    URL is fetched through the same polite fetcher and dated. Freshness is only
    claimed when a date is actually found: an undatable section is recorded as
    `unknown` and does not qualify, rather than being assumed fresh.
    """
    if not editorial_urls:
        return False, None

    page = fetcher.get(editorial_urls[0])
    if page is None:
        return False, EDITORIAL_DATE_UNKNOWN

    found = detect_last_post_date(page)
    if not found:
        return False, EDITORIAL_DATE_UNKNOWN
    try:
        posted = date.fromisoformat(found)
    except ValueError:
        return False, EDITORIAL_DATE_UNKNOWN

    age_days = ((today or date.today()) - posted).days
    return age_days <= EDITORIAL_MAX_AGE_DAYS, found


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
            editorial_last_post=None,
        )

    text = visible_text(html)

    affinity, evidence = detect_sunreef_affinity(text)
    length_ft = detect_max_length_ft(text)
    segment_evidence = f"max_detected_length_ft={length_ft}" if length_ft else None
    editorial_urls = find_editorial_urls(html, url)
    has_editorial, editorial_last_post = _editorial_recency(fetcher, editorial_urls)
    has_newsletter, newsletter_evidence = detect_newsletter(html)

    verdict = dict(
        robots_allowed=True, affinity=affinity, evidence=evidence,
        segment_evidence=segment_evidence, has_editorial=has_editorial,
        has_newsletter=has_newsletter, newsletter_evidence=newsletter_evidence,
        editorial_last_post=editorial_last_post,
    )

    if length_ft is None or length_ft < MIN_LENGTH_FT:
        return _save(
            conn, broker_id, qualified=False, reason="below_length_threshold",
            **verdict,
        )

    if not has_editorial and not has_newsletter:
        return _save(
            conn, broker_id, qualified=False, reason="no_publishing_channel",
            **verdict,
        )

    return _save(conn, broker_id, qualified=True, reason="passed", **verdict)
