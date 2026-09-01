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


#: broker domain -> the one angle `drafting.draft_for_broker` would have
#: persisted for it (spec §5 Stage 4: only the chosen angle is kept, not the
#: full candidate set `AngleClient.propose` returns).
_ANGLES = {
    "meridian-yacht.invalid": dict(
        title="What “Bluewater Ready” Actually Costs a First-Time Catamaran Owner",
        premise=(
            "Most first-time buyers price a catamaran against the sticker on "
            "the flybridge, not against what it costs to make it genuinely "
            "capable of an ocean passage -- the systems, the refit line "
            "items, and the ownership mindset that separate a coastal "
            "cruiser from a bluewater one."
        ),
        audience_value=(
            "Helps a first-time buyer budget and negotiate with eyes open, "
            "instead of discovering the real cost of ocean-readiness only "
            "after closing."
        ),
        sunreef_relevance=(
            "Names a Sunreef model alongside the broker's own delivery "
            "experience as one example of an “owner's version” "
            "layout, without making the piece about Sunreef."
        ),
        score=0.83,
    ),
    "anchorbay.invalid": dict(
        title="Why Haul-Out Timing Matters More Than Slip Fees on the Great Lakes",
        premise=(
            "Owners who chase the cheapest slip often lose more to a rushed "
            "haul-out and improper winterization than they saved in fees -- "
            "timing the haul-out around the lake's actual freeze pattern "
            "protects the investment more than marina shopping does."
        ),
        audience_value=(
            "Gives Great Lakes families a practical seasonal-storage "
            "framework so they stop treating haul-out as an afterthought."
        ),
        sunreef_relevance=(
            "Mentions a Sunreef catamaran among multihulls that need "
            "independent per-hull winterization, without making the piece "
            "about Sunreef."
        ),
        score=0.71,
    ),
}

#: broker domain -> {"long": body, "short": body or absent}. Realistic
#: ~500-word articles and ~150-word condensations in the register each
#: broker's seeded voice_profile describes -- the point of this fixture is
#: for the operator to judge output of this shape, so filler text would
#: defeat it. `anchorbay.invalid` deliberately has no "short" key: it is the
#: degraded state (long draft written, short condensation failed) that
#: `bce redraft` exists to repair, and the draft viewer must show that
#: honestly rather than a blank panel.
_DRAFTS = {
    "meridian-yacht.invalid": dict(
        long=(
            "Every season we meet a buyer who has already decided on a "
            "catamaran and is now negotiating price against a number they "
            "saw on a builder's website. That number describes a boat as it "
            "left the yard, not a boat ready to cross an ocean. The gap "
            "between those two conditions is where first-time owners get "
            "their most expensive surprises -- not in the negotiation, but "
            "in the eighteen months after closing, when the boat that "
            "looked turnkey at the dock reveals every system it still needs "
            "before a genuine bluewater passage makes sense.\n\n"
            "Start with power and water independence, not sail area. A "
            "catamaran built for charter service is provisioned for a week "
            "between marinas, with generator hours and shore power filling "
            "in the gaps. Bluewater cruising asks a different question: can "
            "the house bank carry the watermaker, the autopilot, and the "
            "refrigeration through three consecutive overcast days without "
            "running the engines? Buyers who skip this arithmetic end up "
            "retrofitting solar arrays and lithium banks at anchor, at "
            "double the cost and half the warranty coverage of specifying "
            "it before delivery. A proper survey should price this gap in "
            "dollars, not adjectives.\n\n"
            "The refit list itself is rarely dramatic -- it is long. "
            "Standing rigging inspection intervals, a flybridge helm "
            "station rated for open-ocean spray rather than harbor sun, "
            "ground tackle sized for genuine anchorages instead of marina "
            "overnights, and watertight bulkhead checks that a coastal "
            "survey never touches. Few of these show up in a listing "
            "photo. A broker who has actually delivered boats offshore can "
            "walk a buyer through which items are cosmetic and which are "
            "the difference between a comfortable passage and a miserable "
            "one, and price each honestly rather than folding them into "
            "“as is.”\n\n"
            "Ownership mindset matters as much as equipment. A week "
            "chartering someone else's catamaran teaches you almost "
            "nothing about running your own systems at 2 a.m. in a squall, "
            "because a charter crew has already solved every problem you "
            "never saw. Builders like Sunreef increasingly offer an "
            "“owner's version” layout precisely because this gap "
            "is well understood in the industry -- the difference is "
            "whether a buyer treats that layout as a finished product or "
            "as the starting point for genuine sea trials before the boat "
            "ever leaves for open water.\n\n"
            "This is not a reason to walk away from a catamaran purchase "
            "-- it is a reason to walk in with a checklist instead of a "
            "brochure. When we sit down with a first-time buyer, the "
            "conversation starts with how the boat will actually be used: "
            "coastal weekends, seasonal charter management, or a genuine "
            "bluewater departure two years from now. That answer changes "
            "the refit priorities, the survey scope, and the number that "
            "actually belongs in a budget. Buyers who ask these questions "
            "before signing spend less in year two than buyers who "
            "discover them at anchor."
        ),
        short=(
            "What “Bluewater Ready” Actually Costs\n\n"
            "Most first-time catamaran buyers price the boat they see at "
            "the show, not the boat that can actually cross an ocean. The "
            "gap between the two is where new owners get their most "
            "expensive surprises. A charter-provisioned catamaran carries "
            "enough power and water independence for a week between "
            "marinas -- bluewater cruising asks whether the house bank can "
            "run the watermaker, autopilot, and refrigeration through three "
            "overcast days without the engines. The refit list that closes "
            "that gap is rarely dramatic, just long: rigging inspection "
            "intervals, a flybridge helm built for open-ocean spray, proper "
            "ground tackle, watertight bulkhead checks. Builders like "
            "Sunreef now sell “owner's version” layouts because "
            "the industry knows this gap exists. The fix is not avoiding a "
            "catamaran purchase -- it is walking in with a checklist, not "
            "a brochure, and pricing ocean-readiness honestly before you "
            "sign."
        ),
    ),
    "anchorbay.invalid": dict(
        long=(
            "Every fall, the same conversation happens at the club: "
            "someone found a slip forty miles up the shore for two hundred "
            "dollars less than the marina near their cottage, and they're "
            "ready to move the boat. What that conversation skips is "
            "timing. A cheaper slip that pulls your haul-out into late "
            "October instead of mid-September isn't a discount -- it's a "
            "bet against an early freeze, and on these lakes that bet "
            "doesn't always pay off. Families who've owned a catamaran "
            "here for more than one season already know: the real cost of "
            "freshwater cruising isn't the fee, it's the calendar.\n\n"
            "Freshwater is less forgiving than it looks. Ice doesn't just "
            "sit on the surface -- it works into hull fittings, seacocks, "
            "and anything holding water that wasn't properly winterized. A "
            "haul-out rushed because a slip contract ran long, or delayed "
            "because a hauling slot filled up, leaves systems exposed to a "
            "freeze they were never built for. The families who avoid "
            "trouble aren't the ones who found the cheapest slip fees. "
            "They're the ones who booked their haul-out date before they "
            "booked the slip, and built the whole season's plan around "
            "it.\n\n"
            "This matters even more on a catamaran than a monohull, and "
            "it's worth saying plainly: twin hulls mean twin sets of "
            "everything below the waterline -- two sets of thru-hulls, two "
            "engine rooms, two bilges to check before the cold sets in. A "
            "Sunreef or a similarly built multihull needs a winterization "
            "checklist that accounts for both hulls independently, not a "
            "single pass that assumes symmetry will save time. Skipping a "
            "hull because “it's probably the same as the other "
            "side” is exactly how a cracked fitting gets discovered in "
            "April instead of October, at ten times the repair cost.\n\n"
            "This does not need to be complicated. Talk to your yard about "
            "their actual haul-out schedule before you sign a slip "
            "contract, not after. Ask what happens if an early cold snap "
            "moves the schedule up a week -- plenty of yards will, and "
            "plenty of owners find out the hard way that their contract "
            "didn't cover it. A slip forty miles up the shore might still "
            "be the right call. Just make sure the number you're comparing "
            "includes what a late haul-out could cost, not only what an "
            "early one saves.\n\n"
            "Every season on these lakes rewards patience over shortcuts, "
            "and haul-out planning is where that shows up first. The "
            "owners we hear from years later aren't the ones who found the "
            "best fee -- they're the ones whose boat came out of winter "
            "storage exactly the way it went in. That's worth more than "
            "two hundred dollars in September, and it's the first thing "
            "worth asking about before the slip contract, not after."
        ),
        # No "short" key: condensation failed for this broker (the
        # degraded state `bce redraft` repairs).
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


def _insert_angle(conn: sqlite3.Connection, broker_id: int, angle: dict) -> int:
    cursor = conn.execute(
        "INSERT INTO angle (broker_id, title, premise, audience_value, "
        "sunreef_relevance, score) VALUES (?,?,?,?,?,?)",
        (
            broker_id, angle["title"], angle["premise"],
            angle["audience_value"], angle["sunreef_relevance"], angle["score"],
        ),
    )
    return cursor.lastrowid


def _insert_draft(conn: sqlite3.Connection, angle_id: int, body: str, fmt: str) -> None:
    # Mirrors `drafting.draft_for_broker`: status is always 'pending_review'
    # -- nothing here has been through §10.3's originality gates or §3's
    # editorial value test, and no seed row ever carries a human reviewer.
    conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
        "VALUES (?,?,?,?,?)",
        (angle_id, body, len(body.split()), "pending_review", fmt),
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
        angle = _ANGLES.get(row["domain"])
        if angle is not None:
            angle_id = _insert_angle(conn, broker_id, angle)
            drafts = _DRAFTS.get(row["domain"], {})
            if "long" in drafts:
                _insert_draft(conn, angle_id, drafts["long"], "long")
            if "short" in drafts:
                _insert_draft(conn, angle_id, drafts["short"], "short")
    conn.commit()
    return inserted
