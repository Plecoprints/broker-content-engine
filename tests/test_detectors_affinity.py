from bce.detectors import detect_sunreef_affinity


def test_no_mention_returns_none_level():
    level, evidence = detect_sunreef_affinity("We broker fine catamarans.")
    assert level == "none"
    assert evidence == ""


def test_bare_mention_returns_mentions():
    level, evidence = detect_sunreef_affinity(
        "We admire what Sunreef has done for luxury multihulls."
    )
    assert level == "mentions"
    assert "Sunreef" in evidence


def test_mention_near_listing_marker_returns_lists_inventory():
    level, evidence = detect_sunreef_affinity(
        "Sunreef 80 Eco — price on application. Contact our team."
    )
    assert level == "lists_inventory"
    assert "Sunreef" in evidence


def test_distant_listing_marker_does_not_upgrade():
    text = "Sunreef is a builder we respect. " + ("filler " * 40) + "Boats for sale."
    level, _ = detect_sunreef_affinity(text)
    assert level == "mentions"


def test_case_insensitive():
    level, _ = detect_sunreef_affinity("SUNREEF 60 available now")
    assert level == "lists_inventory"


def test_evidence_is_capped():
    level, evidence = detect_sunreef_affinity("Sunreef " + ("x" * 500))
    assert level == "mentions"
    assert len(evidence) <= 160
