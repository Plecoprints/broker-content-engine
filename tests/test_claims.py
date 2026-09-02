"""§10.4 / §10.9 gate 4: no specific claim about a named Sunreef vessel.

Two things are being tested, and the second matters as much as the first.
A gate this conservative is only usable if it *doesn't* fire on the category
prose the pipeline is supposed to produce -- "a 50ft catamaran offers more
deck space" must sail through. A gate that rejects everything is
indistinguishable from a broken pipeline, and §5b's "when nothing qualifies,
proceed rather than lower the bar" means the failure would be quiet.
"""
import json

import pytest

from bce import claims


# =============================================================================
# Blocks: a named vessel with a specification attached
# =============================================================================

@pytest.mark.parametrize("body,expected_kind", [
    ("The Sunreef 80 Eco carries 46 m2 of solar panels.", "specification"),
    ("The Sunreef 80 Eco carries 46 m² of solar panels.", "specification"),
    ("The Sunreef 100 has a beam of 12.4 m.", "specification"),
    ("The Sunreef 60 displaces 28 tonnes.", "specification"),
    ("The Sunreef Power 80 cruises at 22 knots.", "specification"),
    ("The Sunreef 70 has a range of 1,200 nm.", "specification"),
    ("The Sunreef Power 80 puts out 1,200 hp.", "specification"),
    ("A Sunreef 80 measures 78'.", "specification"),
    ("The Sunreef 100 sleeps 12 guests.", "accommodation"),
    ("The Sunreef 80 offers 5 cabins.", "accommodation"),
    ("The Sunreef 43M is RINA classed.", "certification"),
    ("The Sunreef 80 Eco holds CE Category A.", "certification"),
    ("The Sunreef 100 is built to Lloyd's Register standards.", "certification"),
    ("The Sunreef 70 complies with ISO 12217.", "certification"),
])
def test_a_named_vessel_with_a_spec_is_blocked(body, expected_kind):
    result = claims.check_no_product_claims(body)
    assert result["passes"] is False, f"not blocked: {body}"
    assert result["claims"][0]["kind"] == expected_kind


def test_a_claim_crossing_a_sentence_boundary_is_still_caught():
    """The common shape in real prose, and the reason this is a proximity
    test rather than a per-sentence one."""
    body = "The Sunreef 80 Eco is a remarkable boat. It carries 46 m2 of solar."
    assert claims.check_no_product_claims(body)["passes"] is False


@pytest.mark.parametrize("vessel", [
    "Sunreef 80", "Sunreef 80 Eco", "Sunreef Eco 80", "Sunreef Power 80",
    "Sunreef Supreme 68", "Sunreef 43M", "Sunreef Zero Cat", "Ultima 111",
])
def test_every_vessel_naming_form_is_recognised(vessel):
    body = f"The {vessel} reaches 20 knots."
    assert claims.check_no_product_claims(body)["passes"] is False, vessel


def test_the_shorthand_a_draft_slips_into_is_recognised():
    """Having introduced the boat, prose drops the brand: "the 80 Eco"."""
    body = "The 80 Eco carries 46 m2 of solar."
    assert claims.check_no_product_claims(body)["passes"] is False


# =============================================================================
# Passes: the category prose this pipeline is supposed to produce
# =============================================================================

@pytest.mark.parametrize("body", [
    # No named vessel at all -- the bare company name is not in scope (§10.4).
    "Sunreef builds catamarans in Gdansk. A 60ft catamaran costs more to refit.",
    "Sunreef has been building catamarans for 20 years.",
    # Ordinary category writing, the bulk of what every angle produces.
    "A 50ft catamaran offers more deck space than a monohull of the same length.",
    "Expect 12 knots of boat speed in 18 knots of true wind on a cruising cat.",
    "Insurance on a 60ft catamaran runs 1.5% of hull value annually.",
    "Most owners find 4 cabins is the practical minimum for chartering.",
    # A named vessel with no specification attached is fine.
    "The Sunreef 80 Eco is worth seeing at Cannes this year.",
    "Owners of the Sunreef 100 tend to cruise the Caribbean in winter.",
    # Empty and trivial input.
    "",
    "A short paragraph about catamarans.",
])
def test_category_prose_is_not_blocked(body):
    result = claims.check_no_product_claims(body)
    assert result["passes"] is True, f"false positive on: {body!r} -> {result['claims']}"


def test_a_model_designator_is_not_read_as_its_own_specification():
    """`Sunreef 43M` must not be parsed as "43 metres" -- otherwise merely
    naming a boat would trip the gate and no draft could ever mention one."""
    assert claims.check_no_product_claims("The Sunreef 43M is a fine yacht.")["passes"]
    assert claims.check_no_product_claims("We admire the Sunreef 80.")["passes"]


def test_a_spec_far_from_the_vessel_does_not_collide_with_it():
    """A 2,300-word pillar will mention a boat in one place and a generic
    figure in another; only genuine proximity is a claim."""
    body = (
        "The Sunreef 80 Eco was launched in Gdansk. "
        + ("Filler sentence about cruising grounds. " * 20)
        + "A typical cruising catamaran carries 30 m2 of solar."
    )
    assert claims.check_no_product_claims(body)["passes"] is True


def test_the_proximity_boundary_is_the_named_constant():
    """Pinned so a change to PROXIMITY_CHARS is a deliberate decision with a
    failing test behind it, not a quiet retuning of a Critical-risk gate."""
    near = "The Sunreef 80 Eco. " + ("x" * (claims.PROXIMITY_CHARS - 60)) + " 46 m2."
    far = "The Sunreef 80 Eco. " + ("x" * (claims.PROXIMITY_CHARS + 200)) + " 46 m2."
    assert claims.check_no_product_claims(near)["passes"] is False
    assert claims.check_no_product_claims(far)["passes"] is True


# =============================================================================
# The evidence, which is the half a human acts on
# =============================================================================

def test_the_gate_reports_what_tripped_it():
    body = "The Sunreef 80 Eco carries 46 m2 of solar across the bimini."
    claim = claims.check_no_product_claims(body)["claims"][0]
    assert claim["vessel"] == "Sunreef 80 Eco"
    assert claim["claim"] == "46 m2"
    assert claim["kind"] == "specification"
    assert "46 m2" in claim["snippet"] and "Sunreef 80 Eco" in claim["snippet"]


def test_every_claim_is_reported_not_just_the_first():
    body = "The Sunreef 80 Eco carries 46 m2 of solar, sleeps 8 guests, and is RINA classed."
    kinds = {c["kind"] for c in claims.check_no_product_claims(body)["claims"]}
    assert kinds == {"specification", "accommodation", "certification"}


def test_the_evidence_is_json_serialisable():
    """It is persisted to `draft.product_claims_found` as JSON."""
    body = "The Sunreef 80 Eco carries 46 m2 of solar."
    result = claims.check_no_product_claims(body)
    assert json.loads(json.dumps(result["claims"])) == result["claims"]


# =============================================================================
# The limitation, recorded as a test so it is a known gap and not a surprise
# =============================================================================

def test_an_undesignated_vessel_evades_the_gate():
    """Documented in the module docstring and in §10.9: prose that describes a
    boat without naming it is not caught. This test exists so the gap is
    asserted rather than assumed -- if someone later widens the gate to cover
    it, this test failing is the signal to update the docs and §10.9's claim
    that sampling stays at 100% for the first pilot.
    """
    body = "Their largest sailing catamaran carries 46 m2 of solar."
    assert claims.check_no_product_claims(body)["passes"] is True
