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
            "capable of an ocean passage — the systems, the refit line "
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
            "haul-out and improper winterization than they saved in fees — "
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

#: broker domain -> {"long": body, "medium": body, "short": body}, keys
#: absent where the format was never written. Realistic ~500-word "pillar"
#: placeholders, ~600-word regular-post condensations, and ~150-word
#: newsletter condensations in the register each broker's seeded
#: voice_profile describes — the point of this fixture is for the operator
#: to judge output of this shape, so filler text would defeat it.
#:
#: Only `meridian-yacht.invalid` (the fully-profiled broker) has a "medium"
#: key: spec v0.6 §5 added the format, and seeding it here lets the draft
#: viewer show all three panels for at least one broker with no API spend.
#: `anchorbay.invalid` deliberately has no "short" key (and, unchanged by
#: this task, no "medium" key either): it is the degraded state (long draft
#: written, other formats' condensation failed) that `bce redraft` exists to
#: repair, and the draft viewer must show that honestly rather than a blank
#: panel.
_DRAFTS = {
    "meridian-yacht.invalid": dict(
        long=(
            "Most of our best client conversations start with a number that's "
            "wrong. A first-time buyer walks in having priced a catamaran against "
            "the sticker on the builder's website — the price of a boat as it "
            "left the yard, not a boat ready for open water. That gap is where "
            "new owners find their most expensive surprises, and it rarely shows "
            "up at the negotiating table. It shows up eighteen months later, at "
            "anchor, when the turnkey boat they closed on reveals every system it "
            "still needs before a genuine bluewater passage makes sense. We see "
            "the same pattern often enough that it is worth writing down, before "
            "the first sea trial rather than after.\n\n"
            "Start with why a catamaran at all, because the answer shapes "
            "everything that follows. A well-built multihull in the 60-to-80-foot "
            "range trades the deep, ballasted keel of a monohull for beam and "
            "buoyancy: two slender hulls carrying the boat's weight instead of "
            "one heavy one, connected by a bridgedeck that has to clear the water "
            "by enough margin to avoid slamming in a head sea. Builders differ "
            "enormously in how they solve that tradeoff. Bridgedeck clearance, "
            "hull shape forward, and the weight distribution between the hulls "
            "and the deck all trade off load capacity against motion comfort, and "
            "a buyer who only compares beam and saloon headroom between two boats "
            "is comparing the least important numbers on the spec sheet. "
            "Structural laminate schedules, core materials in the hulls versus "
            "the deck, and how a builder handles chainplate and rig loads where "
            "they transfer into a composite structure matter far more to how the "
            "boat ages over a decade of ownership than anything visible on a "
            "walk-through. A surveyor who has actually opened up a ten-year-old "
            "catamaran's bilges knows which builders' hulls come out clean and "
            "which come out needing a rebuild, and that knowledge rarely makes it "
            "into a listing description. Blister history, print-through along the "
            "hull sides, and how a yard documents its own lay-up schedule are all "
            "fair questions to ask before an offer, not after a deposit.\n\n"
            "Power and water independence is where the gap between “charter "
            "ready” and “ocean ready” shows up first, and it is not about sail "
            "area. A catamaran provisioned for charter service is built for a "
            "week between marinas, with generator hours and shore power filling "
            "in the gaps between guest changeovers. Bluewater cruising asks a "
            "different, harder question: can the house bank carry the watermaker, "
            "the autopilot, and the refrigeration through three consecutive "
            "overcast days without running the engines? Buyers who skip that "
            "arithmetic end up retrofitting solar arrays and lithium banks at "
            "anchor, typically at close to double the cost and with half the "
            "integration quality of specifying it properly before delivery. A "
            "proper survey should price this gap in dollars, not adjectives — "
            "“well equipped” on a listing sheet is not a number anyone can "
            "actually budget against, and a good broker will make a seller "
            "quantify it rather than let the phrase stand. Amp-hour budgeting is "
            "not difficult arithmetic, but almost nobody does it before signing: "
            "add up what the fridge, the autopilot, the watermaker, and basic "
            "electronics draw over twenty-four hours, compare that against what "
            "the house bank and charging sources can actually replace in a day "
            "with limited sun, and the gap between “equipped” and “independent” "
            "becomes a number rather than a feeling.\n\n"
            "The refit list itself is rarely dramatic. It is just long, and none "
            "of it shows up in a listing photo. Standing rigging inspection "
            "intervals that a charter operator let slide because the boat never "
            "left protected water. A flybridge helm station built and upholstered "
            "for harbor sun rather than open-ocean spray, which means resealing "
            "electronics and replacing switch panels sooner than the boat's age "
            "would suggest. Ground tackle sized for a marina overnight rather "
            "than a genuine anchorage, which matters enormously the first time "
            "weather forces a boat to sit on its hook through a real blow. "
            "Watertight bulkhead checks that a coastal survey never touches "
            "because a coastal survey never needs to. Sacrificial anodes and "
            "through-hull condition, easy to defer on a boat that rarely leaves a "
            "marina berth and expensive to discover mid-season once it does. A "
            "broker who has actually delivered boats offshore, rather than just "
            "sold them, can walk a buyer through which items on that list are "
            "cosmetic and which separate a comfortable passage from a genuinely "
            "dangerous one — and price each honestly instead of folding the "
            "whole list into “as is” and letting the buyer discover the "
            "difference at sea.\n\n"
            "Paperwork rarely gets the same attention as equipment, and it "
            "should. CE certification and class society documentation determine "
            "which waters a boat can legally operate in and which insurers will "
            "underwrite it without exclusions, and a boat that changed flag "
            "registration once or twice in its life needs that history checked, "
            "not assumed. Warranty transfer on major systems — engines, "
            "generators, watermakers — is negotiable at the point of sale far "
            "more often than buyers realize, and a broker who pushes for it "
            "before closing routinely saves a new owner several boat-yard "
            "invoices in the first eighteen months. VAT status inside EU waters "
            "is its own question entirely, and getting it wrong is one of the few "
            "mistakes on this list that a good survey cannot catch after the fact "
            "— it has to be confirmed with the seller's documentation before an "
            "offer goes in, not discovered at the next haul-out.\n\n"
            "Layout matters as much as equipment, and this is where the "
            "difference between a charter-configured boat and what builders now "
            "call an “owner's version” becomes concrete rather than a marketing "
            "phrase. A charter layout maximizes cabin count and guest privacy, "
            "because a charter operator's revenue is a function of berths sold "
            "per week. An owner's version typically trades one or two cabins for "
            "a larger owner's suite, a proper day head near the cockpit, and "
            "stowage volume in places a charter boat gives over to another cabin "
            "— because the owner's actual priorities are entirely different from "
            "a week-long guest's. Builders like Sunreef increasingly offer this "
            "owner's-version option precisely because the industry understands "
            "the gap between the two use cases; the practical question for a "
            "buyer is not which layout looks better in a walkthrough video, but "
            "which one still works for the family after year three, once the "
            "novelty of extra guest cabins has worn off and the stowage for "
            "provisioning, spares, and gear has become the thing that actually "
            "matters day to day. Galley-up versus galley-down is its own version "
            "of the same tradeoff — sociability and cockpit connection against "
            "dedicated storm-proof cooking space — and the right answer depends "
            "far more on how a family actually intends to sail than on which one "
            "photographs better.\n\n"
            "Sea-keeping is the part of a catamaran that is hardest to evaluate "
            "from a dock, and it is also the part that determines whether a first "
            "bluewater passage is memorable for the right reasons. Two things "
            "matter more than most buyers expect going in: motion at anchor, "
            "which for most owners is where the boat actually spends the "
            "overwhelming majority of its life, and motion underway in a beam "
            "sea, which is the point of sail most catamarans handle least "
            "gracefully. A boat with generous bridgedeck clearance and "
            "well-shaped forward sections will ride a chop with far less slamming "
            "than one optimized purely for interior volume, and that difference "
            "is felt every single night at anchor in a place with any fetch at "
            "all, not just on a passage. Daggerboards versus fixed mini-keels is "
            "its own tradeoff — better upwind performance and shallower leeway "
            "against simplicity, lower maintenance, and shallow-draft anchoring "
            "access — and neither answer is wrong, but a buyer should understand "
            "which one they are choosing and why, rather than treating it as a "
            "spec-sheet footnote. Righting-moment behavior also differs "
            "meaningfully from a monohull's: a catamaran does not heel to warn a "
            "crew the way a ballasted boat does, so the systems and habits that "
            "keep a multihull within its safe operating envelope in a blow are a "
            "genuinely different skill set, one worth learning at the dock rather "
            "than discovering underway.\n\n"
            "For a broker working the Mediterranean, cruising-grounds context is "
            "not an abstraction; it is the difference between a boat that gets "
            "used and one that sits at the dock. The Mediterranean's marina "
            "infrastructure was largely built for monohulls, and a wide-beam "
            "catamaran can find berthing tighter and pricier than the brochure "
            "suggested, particularly in the high-season Balearics and along the "
            "French and Italian Riviera. Meltemi season in the Aegean rewards a "
            "boat that tracks well downwind and has ground tackle sized for an "
            "unplanned anchorage when a marina reservation falls through. This "
            "does not change whether a catamaran is the right choice — for most "
            "owners in this segment it still is — but it changes which catamaran "
            "is the right choice, and a buyer who has only ever chartered in flat "
            "summer conditions has not actually seen the boat's harder edges yet.\n\n"
            "Seasonal lay-up planning is the Mediterranean-specific version of a "
            "problem every cruising ground has in its own form. Haul-out slots at "
            "the well-regarded yards fill up months ahead of the autumn rush, and "
            "a boat left in the water over a winter it was not rigged for arrives "
            "at spring commissioning with problems a proper lay-up would have "
            "prevented. Owners who plan the haul-out date before they plan the "
            "season's itinerary consistently spend less on spring commissioning "
            "than owners who treat winter storage as an afterthought, and the "
            "same logic that applies to system familiarization applies here: "
            "booking the yard early is cheap, and discovering there is no slot "
            "left in October is not.\n\n"
            "Ownership economics deserve the same honesty as the refit list. "
            "Catamarans in this size range hold value differently than monohulls "
            "— generally better through the first decade, provided the boat has "
            "been properly maintained and the systems above have been addressed "
            "rather than deferred — but marina and haul-out costs for a "
            "wide-beam boat run meaningfully higher than for a monohull of "
            "similar length, and that gap compounds every year of ownership. "
            "Insurance follows the same pattern: underwriters increasingly "
            "understand multihulls, but a policy priced against a coastal-only "
            "boat and then used for genuine bluewater passages is a real gap "
            "worth closing before departure, not after a claim. A charter "
            "management arrangement can offset some of the annual carrying cost "
            "for owners who want their boat working part of the year, but it also "
            "accelerates wear on exactly the systems — watermakers, generators, "
            "air conditioning — that are most expensive to replace, so the "
            "offset is real but it is not free, and a buyer weighing that "
            "tradeoff should run the actual numbers rather than the marketing "
            "pitch a charter company will offer.\n\n"
            "Ownership mindset matters as much as any of the equipment above. A "
            "week chartering someone else's catamaran teaches almost nothing "
            "about running your own systems at two in the morning in a squall, "
            "because a charter crew has already solved every problem before a "
            "guest ever notices it existed. This is also where a good delivery "
            "skipper earns their fee twice over: once actually getting the boat "
            "to its home port, and again teaching the new owner what each system "
            "sounds like and feels like under real load, well before the first "
            "genuine passage. Owners who skip that second part tend to discover "
            "their systems' actual limits at the worst possible moment — "
            "mid-crossing, at night — rather than at the dock with a "
            "professional standing beside them and time to explain what is normal "
            "and what is not.\n\n"
            "This is not a reason to walk away from a catamaran purchase. It is a "
            "reason to walk in with a checklist instead of a brochure. When we "
            "sit down with a first-time buyer, the conversation starts with how "
            "the boat will actually be used — coastal weekends, seasonal charter "
            "management, or a genuine bluewater departure two years from now — "
            "because that answer changes the refit priorities, the survey scope, "
            "and the number that actually belongs in a budget. Buyers who ask "
            "these questions before signing consistently spend less in year two "
            "than buyers who discover the answers at anchor, and they are, "
            "without exception, the ones who come back to us for the next boat."
        ),
        # A regular-length blog post condensed from the "long" pillar piece
        # above — roughly this broker's typical_word_count (620), in the
        # same "polished and consultative" register and carrying the same
        # claims, standing in for a real write_medium output.
        medium=(
            "Most of our best client conversations start with a number "
            "that's wrong. A first-time buyer walks in having priced a "
            "catamaran against the sticker on the builder's website — the "
            "price of a boat as it left the yard, not a boat ready for open "
            "water. That gap is where new owners find their most expensive "
            "surprises, and it rarely shows up at the negotiating table. It "
            "shows up eighteen months later, at anchor, when the turnkey "
            "boat they closed on reveals every system it still needs before "
            "a genuine bluewater passage makes sense. We see the same "
            "pattern often enough that it is worth saying plainly, before "
            "the first sea trial rather than after.\n\n"
            "Start with power and water independence, not sail area. A "
            "catamaran provisioned for charter service is built for a week "
            "between marinas, with generator hours and shore power filling "
            "the gaps. Bluewater cruising asks a harder question: can the "
            "house bank run the watermaker, the autopilot, and the "
            "refrigeration through three overcast days without the "
            "engines? Buyers who skip that arithmetic end up retrofitting "
            "solar arrays and lithium banks at anchor, at roughly double "
            "the cost of specifying it before delivery. A proper survey "
            "should price this gap in dollars, not adjectives — “well "
            "equipped” on a listing sheet is not a number anyone can "
            "budget against.\n\n"
            "The refit list that closes this gap is rarely dramatic — it "
            "is just long. Standing rigging inspection intervals. A "
            "flybridge helm station rated for open-ocean spray rather than "
            "harbor sun. Ground tackle sized for genuine anchorages "
            "instead of marina overnights. Watertight bulkhead checks a "
            "coastal survey never touches. Nothing on this list shows up in a "
            "listing photo, and a broker who has actually delivered boats "
            "offshore can walk a buyer through which items are cosmetic "
            "and which separate a comfortable passage from a miserable one "
            "— and price each honestly instead of folding it all into "
            "“as is.”\n\n"
            "Ownership mindset matters as much as equipment. A week "
            "chartering someone else's catamaran teaches almost nothing "
            "about running your own systems at 2 a.m. in a squall, because "
            "a charter crew has already solved every problem you never "
            "saw. Builders like Sunreef increasingly offer an “owner's "
            "version” layout for exactly this reason — the difference is "
            "whether a buyer treats that layout as a finished product or "
            "as the starting point for genuine sea trials before the boat "
            "ever leaves for open water.\n\n"
            "This is also where a good delivery skipper earns their fee "
            "twice over: once getting the boat to its home port, and "
            "again teaching the new owner what each system actually "
            "sounds like and feels like under load, well before the first "
            "real passage. Owners who skip this step tend to discover "
            "their systems' limits at the worst possible moment — "
            "mid-crossing, at night, rather than at the dock with a "
            "professional standing beside them.\n\n"
            "Nothing here is a reason to walk away from a catamaran "
            "purchase. It is a reason to walk in with a checklist instead "
            "of a brochure. When we sit down with a first-time buyer, the "
            "conversation starts with how the boat will actually be used "
            "— coastal weekends, seasonal charter management, or a "
            "genuine bluewater departure two years out. That answer "
            "changes the refit priorities, the survey scope, and the "
            "number that actually belongs in a budget. The buyers who ask "
            "these questions before signing spend less in year two than "
            "the ones who discover them at anchor — and they are, "
            "without exception, the ones who come back to us for the next "
            "boat, turnkey checklist in hand instead of a brochure."
        ),
        short=(
            "What “Bluewater Ready” Actually Costs\n\n"
            "Most first-time catamaran buyers price the boat they see at "
            "the show, not the boat that can actually cross an ocean. The "
            "gap between the two is where new owners get their most "
            "expensive surprises. A charter-provisioned catamaran carries "
            "enough power and water independence for a week between "
            "marinas — bluewater cruising asks whether the house bank can "
            "run the watermaker, autopilot, and refrigeration through three "
            "overcast days without the engines. The refit list that closes "
            "that gap is rarely dramatic, just long: rigging inspection "
            "intervals, a flybridge helm built for open-ocean spray, proper "
            "ground tackle, watertight bulkhead checks. Builders like "
            "Sunreef now sell “owner's version” layouts because "
            "the industry knows this gap exists. The fix is not avoiding a "
            "catamaran purchase — it is walking in with a checklist, not "
            "a brochure, and pricing ocean-readiness honestly before you "
            "sign."
        ),
    ),
    "anchorbay.invalid": dict(
        long=(
            "Every fall, the same conversation happens at the club: someone found "
            "a slip forty miles up the shore for two hundred dollars less than "
            "the marina near their cottage, and they're ready to move the boat. "
            "What that conversation skips is timing. A cheaper slip that pulls "
            "your haul-out into late October instead of mid-September isn't a "
            "discount — it's a bet against an early freeze, and on these lakes "
            "that bet doesn't always pay off. Families who've owned a catamaran "
            "here for more than one season already know: the real cost of "
            "freshwater cruising isn't the fee, it's the calendar. We write this "
            "down every autumn because the lesson never seems to travel from one "
            "owner to the next on its own.\n\n"
            "Freshwater is a genuinely different environment from the coastal "
            "cruising most catamaran literature is written for, and it is worth "
            "being specific about why. There is no salt to slow galvanic "
            "corrosion the way it does on a coastal boat, but freshwater brings "
            "its own electrolysis risk from stray current and dissimilar metals, "
            "and a boat wired or grounded the way a saltwater yard would do it is "
            "not automatically wired correctly for a freshwater slip. Zinc anodes "
            "wear on a different schedule here than the tables in a coastal "
            "owner's manual assume, and a haul-out inspection that only checks "
            "“are the zincs still there” rather than “are they wearing at the "
            "rate this lake actually produces” misses the actual question. "
            "Nothing here is exotic knowledge, but it is regional knowledge, and "
            "a broker or yard that has only ever worked saltwater boats will not "
            "think to mention it.\n\n"
            "Ice doesn't just sit on the surface — it works into hull fittings, "
            "seacocks, and anything holding water that wasn't properly "
            "winterized. A haul-out rushed because a slip contract ran long, or "
            "delayed because a hauling slot filled up, leaves systems exposed to "
            "a freeze they were never built for. The families who avoid trouble "
            "aren't the ones who found the cheapest slip fees. They're the ones "
            "who booked their haul-out date before they booked the slip, and "
            "built the whole season's plan around it. Fresh water expands roughly "
            "the same way seawater does when it freezes, but a Great Lakes cold "
            "snap arrives faster and holds longer than most first-time owners "
            "expect coming from a milder coastal background, and a winterization "
            "schedule copied from a friend's boat in a warmer climate is not a "
            "plan, it is a guess.\n\n"
            "Water levels are their own regional complication, and one most "
            "first-time owners have never had to think about on salt water. The "
            "Great Lakes run through multi-year high and low cycles that shift "
            "channel depths, breakwall clearances, and even which marinas can "
            "comfortably take a deeper-draft boat, and a chart or a marina's "
            "stated depth from three seasons ago is not something to trust "
            "without a current check. Weed growth in the shallower bays follows "
            "its own seasonal pattern too, thick enough by late summer in some "
            "anchorages to foul an intake or wrap a prop, and owners who cruise "
            "the same familiar bay every July learn to read it, while "
            "first-season owners often do not know to look. Managing either one "
            "is not difficult once an owner knows to watch for it — it is simply "
            "not the kind of thing a coastal sailing background prepares anyone "
            "for, and it rarely comes up in a sales conversation unless someone "
            "thinks to raise it.\n\n"
            "This matters even more on a catamaran than a monohull, and it's "
            "worth saying plainly: twin hulls mean twin sets of everything below "
            "the waterline — two sets of thru-hulls, two engine rooms, two "
            "bilges to check before the cold sets in. A Sunreef or a similarly "
            "built multihull needs a winterization checklist that accounts for "
            "both hulls independently, not a single pass that assumes symmetry "
            "will save time. Skipping a hull because “it's probably the same as "
            "the other side” is exactly how a cracked fitting gets discovered in "
            "April instead of October, at ten times the repair cost. Twin engines "
            "and twin generators, where a boat carries the latter, double the "
            "fuel-system and cooling-system items on the checklist too, and a "
            "yard crew working from a monohull's habits will need to be told "
            "explicitly that a catamaran's list is not half again as long — it "
            "is close to double.\n\n"
            "Build considerations for freshwater catamaran ownership are not "
            "identical to the bluewater conversation a broker on the coast would "
            "have, and buyers coming from a saltwater background sometimes assume "
            "the boat needs less rather than differently. A hull built for salt "
            "exposure often carries more anti-fouling capability than a "
            "freshwater lake actually needs, but the same hull's bridgedeck "
            "clearance and forward sections still matter enormously here, because "
            "Great Lakes chop is fetch-driven and short-period in a way that can "
            "be harder on a boat than a longer ocean swell of the same height. A "
            "boat that rides an Atlantic swell comfortably can still slam "
            "uncomfortably in a two-foot Lake Michigan chop with a six-second "
            "period, and buyers who only ask about the boat's ocean-going "
            "pedigree sometimes overlook the question that actually matters for "
            "how the boat will spend most of its life on these waters. Interior "
            "layout follows from the same logic: a boat built around long-passage "
            "berths and offshore stowage is not automatically the best fit for a "
            "family that spends most weekends at anchor in a sheltered bay and "
            "wants a cockpit and swim platform built for exactly that, and it is "
            "worth asking a broker directly which use case a given boat's layout "
            "was actually optimized for before assuming ocean pedigree translates "
            "cleanly to lake life.\n\n"
            "Documentation and registration carry a cross-border wrinkle here "
            "that a coastal owner never has to think about. A season spent moving "
            "between US and Canadian waters on the Great Lakes means customs "
            "reporting on both sides, and a boat documented or insured only with "
            "a domestic cruising area in mind can find that its paperwork does "
            "not actually match the season its owner wants to sail. This is a "
            "solvable problem, and most owners solve it in their first season "
            "without much drama, but it belongs on the pre-purchase checklist "
            "next to the survey, not on the list of things discovered at a "
            "customs dock on a Saturday morning.\n\n"
            "A week spent chartering a friend's catamaran on a Caribbean vacation "
            "does not prepare a family for their own first spring commissioning "
            "on these lakes, and it is worth saying plainly: a boat that has been "
            "on the hard all winter needs a real shakedown, not just a fuel fill "
            "and a launch. Engines that sat idle for five months, seals that "
            "dried out, and batteries that spent a winter discharging slowly all "
            "deserve a dockside check before the first real weekend out, and "
            "owners who treat launch day as the start of the season rather than "
            "the end of the commissioning process are the ones who end up calling "
            "a mechanic from an anchorage instead of from the slip.\n\n"
            "Great Lakes cruising grounds reward a very particular kind of boat, "
            "and layout tradeoffs that matter little on a coastal charter route "
            "matter a great deal here. Georgian Bay's Thirty Thousand Islands and "
            "the North Channel are dense with shallow, rock-strewn anchorages "
            "that favor a boat with real shoal-draft capability — daggerboards "
            "that retract fully, or a hull shape that tolerates a soft grounding "
            "without drama. A boat optimized purely for open-water "
            "passage-making, with a deep fixed keel or daggerboards that only "
            "partially retract, will find entire cruising grounds effectively "
            "closed to it that a shallower-draft multihull can enter without a "
            "second thought. This is one of the clearest cases where the “right” "
            "catamaran genuinely depends on where it will actually be used, not "
            "on which spec sheet reads most impressively.\n\n"
            "Sea-keeping in Great Lakes conditions deserves its own honest "
            "conversation, because it differs from both coastal and bluewater "
            "sailing in ways that surprise experienced sailors coming from either "
            "background. Lake Superior in a fall gale produces seas that rival "
            "open ocean conditions in height and violence, compressed into a "
            "fetch a fraction of the size, which means the period between waves "
            "is short and the motion is correspondingly sharper. A boat and a "
            "crew both need to respect that these are not “just lakes” in the "
            "dismissive sense some coastal sailors assume before their first "
            "Great Lakes season. At the other extreme, a still summer morning on "
            "a sheltered bay can lull an owner into skipping the weather check "
            "that would have caught an afternoon squall line building over the "
            "open water — these lakes generate their own weather fast, and a "
            "forecast that was accurate at breakfast can be wrong by early "
            "afternoon. Water temperature is its own quiet hazard that a "
            "saltwater background does not prepare anyone for: even in "
            "mid-summer, Lake Superior and Lake Huron stay cold enough that an "
            "unplanned time in the water becomes a real emergency in minutes "
            "rather than an inconvenience, and a family's safety briefing at the "
            "start of the season should say so plainly rather than assume "
            "everyone already knows.\n\n"
            "Ownership economics in this region have their own shape too. Marina "
            "and mooring costs vary enormously between the popular "
            "cottage-country harbors and the quieter ports an hour or two further "
            "out, and a family that anchors their season around one expensive "
            "home marina is paying a premium that a slightly different itinerary "
            "could avoid without sacrificing much. Haul-out and winter storage "
            "costs are a real annual line item here in a way they are not in a "
            "year-round cruising climate, because every boat on these lakes comes "
            "out of the water for several months whether the owner wants it to or "
            "not, and a storage contract signed in a hurry in October usually "
            "costs more than one negotiated in June. Insurance policies also need "
            "a genuine look at lay-up dates and inland-water clauses, since a "
            "policy written with a coastal season in mind may not automatically "
            "match a Great Lakes owner's actual haul-out and launch calendar.\n\n"
            "Resale demand on these lakes is thinner than on either coast, simply "
            "because the pool of Great Lakes catamaran owners is smaller, and "
            "that cuts both ways for a buyer to understand going in. A "
            "well-maintained boat with a documented winterization history sells "
            "to a smaller but genuinely motivated regional audience, and the same "
            "care that keeps a boat's systems healthy through repeated "
            "freeze-thaw cycles is exactly what the next buyer's surveyor will be "
            "looking for — a haul-out and winterization log is not paperwork for "
            "its own sake, it is the thing that actually protects resale value on "
            "a lake-cruised boat in a way it matters less for a boat that never "
            "sees a hard freeze. Owners who keep that record from the first "
            "season rather than starting it in year five consistently get an "
            "easier sale when the time comes.\n\n"
            "This does not need to be complicated. Talk to your yard about their "
            "actual haul-out schedule before you sign a slip contract, not after. "
            "Ask what happens if an early cold snap moves the schedule up a week "
            "— plenty of yards will, and plenty of owners find out the hard way "
            "that their contract didn't cover it. A slip forty miles up the shore "
            "might still be the right call. Just make sure the number you're "
            "comparing includes what a late haul-out could cost, not only what an "
            "early one saves.\n\n"
            "Every season on these lakes rewards patience over shortcuts, and "
            "haul-out planning is where that shows up first. The owners we hear "
            "from years later aren't the ones who found the best fee — they're "
            "the ones whose boat came out of winter storage exactly the way it "
            "went in, with a winterization log a surveyor can trust and a spring "
            "commissioning that turned up nothing worse than a battery to "
            "replace. That's worth more than two hundred dollars in September, "
            "and it's the first thing worth asking about before the slip "
            "contract, not after."
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
    # — nothing here has been through §10.3's originality gates or §3's
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
            if "medium" in drafts:
                _insert_draft(conn, angle_id, drafts["medium"], "medium")
            if "short" in drafts:
                _insert_draft(conn, angle_id, drafts["short"], "short")
    conn.commit()
    return inserted
