"""Example data for the operator UI (spec §9), covering every display state.

Task 1's whole point is a page a human can look at. A fixture that only shows
the happy path would make the template look correct until real data with
NULLs everywhere arrives — so this seeds one broker per edge state from the
task brief's table: qualified/profiled/classified, qualified/profiled with a
failed classification, qualified with no profile at all, three distinct
rejection reasons (one with NULL channel columns), a pending broker, and
brokers spanning both ends of the affinity ordering.

Every domain ends `.invalid` (RFC 2606) so seed data can never resolve or be
mistaken for a real broker. Every name is plain ASCII with no `&`, `<`, `>`,
or the substring "None" — Jinja2 autoescapes the former, and a UI guard
elsewhere checks for the literal string "None" leaking into rendered HTML.
"""
import json
import sqlite3

#: First domain inserted. Idempotency check: if this is already present, the
#: whole batch was seeded before, so nothing is inserted again.
_MARKER_DOMAIN = "meridian-yacht.invalid"

_BROKERS = [
    # Qualified, profiled, classified — the full happy path. Warmest affinity.
    dict(
        name="Meridian Yacht Brokers", domain="meridian-yacht.invalid",
        region="Mediterranean", segment_evidence="max_detected_length_ft=78",
        source="manual", sunreef_affinity="lists_inventory",
        affinity_evidence="lists Sunreef catamarans in current inventory",
        has_editorial=1, has_newsletter=1,
        newsletter_evidence="newsletter signup form in footer",
        editorial_last_post="2026-08-01", qualified=1, qualified_reason="passed",
        robots_allowed=1,
    ),
    # Qualified, profiled, but classification failed: register/themes/
    # audience_signal all NULL even though the row exists and statistics were
    # computed from the collected articles.
    dict(
        name="Coral Harbor Yachts", domain="coralharbor.invalid",
        region="Caribbean", segment_evidence="max_detected_length_ft=65",
        source="manual", sunreef_affinity="unknown",
        affinity_evidence=None,
        has_editorial=1, has_newsletter=0, newsletter_evidence=None,
        editorial_last_post="2026-06-01", qualified=1, qualified_reason="passed",
        robots_allowed=1,
    ),
    # Qualified, not yet profiled — no voice_profile row at all.
    dict(
        name="Blue Horizon Marine", domain="bluehorizon.invalid",
        region="Pacific Northwest", segment_evidence="max_detected_length_ft=70",
        source="manual", sunreef_affinity="mentions",
        affinity_evidence="mentions Sunreef in a fleet comparison article",
        has_editorial=1, has_newsletter=1,
        newsletter_evidence="subscribe box on every article page",
        editorial_last_post="2026-07-15", qualified=1, qualified_reason="passed",
        robots_allowed=1,
    ),
    # Rejected — below_length_threshold.
    dict(
        name="Palmetto Yacht Sales", domain="palmetto-yachts.invalid",
        region="Gulf Coast", segment_evidence="max_detected_length_ft=42",
        source="manual", sunreef_affinity="none",
        affinity_evidence=None,
        has_editorial=1, has_newsletter=0, newsletter_evidence=None,
        editorial_last_post="2026-05-01", qualified=0,
        qualified_reason="below_length_threshold", robots_allowed=1,
    ),
    # Rejected — editorial_recency_undetermined: an editorial section exists
    # but no publication date could be pinned down on any tried URL.
    dict(
        name="Windward Yacht Group", domain="windward-group.invalid",
        region="New England", segment_evidence="max_detected_length_ft=58",
        source="manual", sunreef_affinity="unknown",
        affinity_evidence=None,
        has_editorial=0, has_newsletter=0, newsletter_evidence=None,
        editorial_last_post="unknown", qualified=0,
        qualified_reason="editorial_recency_undetermined", robots_allowed=1,
    ),
    # Rejected — unreachable_or_disallowed: the homepage fetch never
    # succeeded, so `_tri` left every channel column NULL ("never looked"),
    # not False ("looked and found nothing").
    dict(
        name="Sabatini Charter Co", domain="sabatini-charter.invalid",
        region=None, segment_evidence=None,
        source="manual", sunreef_affinity="unknown",
        affinity_evidence=None,
        has_editorial=None, has_newsletter=None, newsletter_evidence=None,
        editorial_last_post=None, qualified=0,
        qualified_reason="unreachable_or_disallowed", robots_allowed=0,
    ),
    # Pending — never run through Stage 2 at all.
    dict(
        name="Trident Yacht Partners", domain="trident-partners.invalid",
        region=None, segment_evidence=None,
        source="manual", sunreef_affinity="unknown",
        affinity_evidence=None,
        has_editorial=None, has_newsletter=None, newsletter_evidence=None,
        editorial_last_post=None, qualified=None, qualified_reason=None,
        robots_allowed=None,
    ),
    # Qualified, profiled, classified — the coldest affinity ("none"), so the
    # ordering and no-hiding/no-badging behaviour has an example at each end.
    dict(
        name="Anchor Bay Yachts", domain="anchorbay.invalid",
        region="Great Lakes", segment_evidence="max_detected_length_ft=61",
        source="manual", sunreef_affinity="none",
        affinity_evidence=None,
        has_editorial=1, has_newsletter=0, newsletter_evidence=None,
        editorial_last_post="2026-07-20", qualified=1, qualified_reason="passed",
        robots_allowed=1,
    ),
]

#: broker domain -> voice_profile row, matching what `bce.profile` writes
#: (json.dumps for the four JSON columns). Only brokers that were actually
#: profiled appear here.
_PROFILES = {
    "meridian-yacht.invalid": dict(
        register="polished and consultative",
        avg_sentence_len=16.2,
        typical_word_count=620,
        structure_pattern={"paragraphs_per_article": 5, "words_per_paragraph": 95},
        vocabulary_markers=["turnkey", "bluewater", "flybridge"],
        themes=["catamaran ownership", "charter management", "refit tips"],
        audience_signal="first-time luxury catamaran buyers",
        sample_quotes=[
            "Owning a catamaran means rethinking how you move through open water."
        ],
        analyzed_at="2026-08-10T09:00:00+00:00",
    ),
    "coralharbor.invalid": dict(
        register=None,
        avg_sentence_len=18.5,
        typical_word_count=850,
        structure_pattern={"paragraphs_per_article": 3, "words_per_paragraph": 120},
        vocabulary_markers=[],
        themes=None,
        audience_signal=None,
        sample_quotes=[],
        analyzed_at="2026-08-11T09:00:00+00:00",
    ),
    "anchorbay.invalid": dict(
        register="warm and community-oriented",
        avg_sentence_len=14.8,
        typical_word_count=540,
        structure_pattern={"paragraphs_per_article": 4, "words_per_paragraph": 88},
        vocabulary_markers=["freshwater cruising", "slip fees", "haul-out"],
        themes=["Great Lakes cruising routes", "seasonal storage"],
        audience_signal="regional freshwater boating families",
        sample_quotes=["The Great Lakes reward patience more than horsepower."],
        analyzed_at="2026-08-12T09:00:00+00:00",
    ),
}


def _insert_broker(conn: sqlite3.Connection, row: dict) -> int:
    cursor = conn.execute(
        "INSERT INTO broker (name, domain, region, segment_evidence, source, "
        "sunreef_affinity, affinity_evidence, has_editorial, has_newsletter, "
        "newsletter_evidence, editorial_last_post, qualified, qualified_reason, "
        "robots_allowed) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            row["name"], row["domain"], row["region"], row["segment_evidence"],
            row["source"], row["sunreef_affinity"], row["affinity_evidence"],
            row["has_editorial"], row["has_newsletter"], row["newsletter_evidence"],
            row["editorial_last_post"], row["qualified"], row["qualified_reason"],
            row["robots_allowed"],
        ),
    )
    return cursor.lastrowid


def _insert_profile(conn: sqlite3.Connection, broker_id: int, profile: dict) -> None:
    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes, analyzed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            broker_id,
            profile["register"],
            profile["avg_sentence_len"],
            profile["typical_word_count"],
            json.dumps(profile["structure_pattern"]),
            json.dumps(profile["vocabulary_markers"])
            if profile["vocabulary_markers"] is not None else None,
            json.dumps(profile["themes"]) if profile["themes"] is not None else None,
            profile["audience_signal"],
            json.dumps(profile["sample_quotes"])
            if profile["sample_quotes"] is not None else None,
            profile["analyzed_at"],
        ),
    )


def seed_example(conn: sqlite3.Connection) -> int:
    """Insert the example brokers, idempotently. Returns how many were inserted.

    Idempotent by checking for the first seed domain before doing anything:
    if it is already present, the whole batch was seeded before and nothing
    is inserted again (a partial re-seed would risk a second voice_profile
    row tripping the table's `broker_id` primary key).
    """
    existing = conn.execute(
        "SELECT 1 FROM broker WHERE domain=?", (_MARKER_DOMAIN,)
    ).fetchone()
    if existing is not None:
        return 0

    inserted = 0
    for row in _BROKERS:
        broker_id = _insert_broker(conn, row)
        inserted += 1
        profile = _PROFILES.get(row["domain"])
        if profile is not None:
            _insert_profile(conn, broker_id, profile)
    conn.commit()
    return inserted
