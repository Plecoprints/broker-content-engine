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
          has_newsletter, newsletter_evidence, editorial_last_post=None,
          visible_text_chars=None):
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
    # `visible_text_chars` is returned, never stored: it describes how well we
    # could *read* the page, not a fact about the broker, and the caller uses
    # it only to warn that a rejection may be a rendering artefact.
    return {
        "qualified": qualified,
        "reason": reason,
        "visible_text_chars": visible_text_chars,
        "render_suspect": (
            not qualified
            and visible_text_chars is not None
            and visible_text_chars < RENDER_SUSPICION_CHARS
        ),
    }


#: Below this much visible text on a page that fetched 200 OK, the verdict is
#: not trustworthy and the operator should look by hand.
#:
#: Spec §7 lists Playwright for "JS-rendered sites (many broker sites are
#: SPA)", but it is not installed and nothing references it: `Fetcher` is
#: httpx only, so a client-rendered site yields its shell and almost no
#: visible text. Every downstream detector then reads an empty page --
#: `detect_max_length_ft` finds no footage and the broker is recorded
#: `below_length_threshold`, which reads as "too small for us" when the truth
#: is "we could not see the page". That is the one wrong conclusion in this
#: stage that would silently remove real brokers from the shortlist, so it is
#: surfaced rather than inferred. A real brokerage homepage carries thousands
#: of characters; 500 is a generous floor for "we saw essentially nothing".
RENDER_SUSPICION_CHARS = 500

#: Cap on how many editorial URLs `_editorial_recency` will fetch per broker.
#: `find_editorial_urls` returns DOM order, not freshness order, so a nav
#: reading "Guides | Blog" would date the evergreen page first and never look
#: further if only the first URL were tried.
MAX_EDITORIAL_URLS_TRIED = 3


def _editorial_recency(fetcher, editorial_urls, *, today=None):
    """(fresh_editorial_channel, recorded_last_post) for spec §4's 12 months.

    A link to a journal proves a link, not a publication, so editorial URLs
    are fetched through the same polite fetcher and dated, in the order
    `find_editorial_urls` returned them (DOM order, not freshness order —
    that ordering is unreliable, which is exactly why a single fetch is not
    trusted here).

    Up to `MAX_EDITORIAL_URLS_TRIED` are tried, but the loop only stops early
    on a **fresh** date — trusting the first *parseable* date, even a stale
    one, would repeat the same DOM-order trust that motivated trying more
    than one URL in the first place: an evergreen `/guides` page with a
    years-old timestamp would shadow an actually-updated blog listed after
    it. So a stale date keeps the search going (bounded at
    `MAX_EDITORIAL_URLS_TRIED`), and the **most recent** date found across
    all tried URLs is what gets recorded and judged. This still costs
    exactly one fetch in the common case — first URL dates fresh — since
    that is the only case that returns early.

    Freshness is only claimed when a date is actually found: if none of the
    tried URLs yield a date, the channel is recorded as `unknown` rather than
    assumed fresh.
    """
    if not editorial_urls:
        return False, None

    today = today or date.today()
    most_recent_posted: date | None = None
    most_recent_found: str | None = None

    for editorial_url in editorial_urls[:MAX_EDITORIAL_URLS_TRIED]:
        page = fetcher.get(editorial_url)
        if page is None:
            continue

        found = detect_last_post_date(page)
        if not found:
            continue
        try:
            posted = date.fromisoformat(found)
        except ValueError:
            continue

        if (today - posted).days <= EDITORIAL_MAX_AGE_DAYS:
            return True, found  # fresh -- settles the verdict, stop here

        if most_recent_posted is None or posted > most_recent_posted:
            most_recent_posted, most_recent_found = posted, found

    if most_recent_found is not None:
        return False, most_recent_found  # stale, but the most recent found

    return False, EDITORIAL_DATE_UNKNOWN


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
        visible_text_chars=len(text),
    )

    if length_ft is None or length_ft < MIN_LENGTH_FT:
        return _save(
            conn, broker_id, qualified=False, reason="below_length_threshold",
            **verdict,
        )

    if not has_editorial and not has_newsletter:
        # `editorial_last_post` fully distinguishes the three shapes of "no
        # qualifying channel", since `_editorial_recency` only returns None
        # when no editorial URLs were found at all:
        #   - None                    -> no editorial URLs at all: genuinely
        #                                 no channel exists.
        #   - EDITORIAL_DATE_UNKNOWN   -> editorial URLs found, but no date
        #                                 could be pinned down on any of them.
        #   - a real ISO date         -> a date *was* found, just stale. The
        #                                 broker has a channel -- it is
        #                                 dormant, not absent -- so this must
        #                                 not share `no_publishing_channel`
        #                                 with the genuinely-no-channel case.
        if editorial_last_post is None:
            reason = "no_publishing_channel"
        elif editorial_last_post == EDITORIAL_DATE_UNKNOWN:
            reason = "editorial_recency_undetermined"
        else:
            reason = "editorial_stale"
        return _save(conn, broker_id, qualified=False, reason=reason, **verdict)

    return _save(conn, broker_id, qualified=True, reason="passed", **verdict)
