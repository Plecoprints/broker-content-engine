from bce.detectors import detect_newsletter, find_editorial_urls


def test_detects_newsletter_signup():
    present, evidence = detect_newsletter("Sign up for our newsletter below.")
    assert present is True
    assert "newsletter" in evidence.lower()


def test_detects_subscribe_wording():
    present, _ = detect_newsletter("Subscribe to receive new listings.")
    assert present is True


def test_detects_mailing_list_across_whitespace():
    present, _ = detect_newsletter("Join our mailing\n    list today.")
    assert present is True


def test_detects_signup_markup():
    present, _ = detect_newsletter('<div class="newsletter-signup"></div>')
    assert present is True


def test_absent_returns_false_and_empty_evidence():
    present, evidence = detect_newsletter("We sell fine catamarans.")
    assert present is False
    assert evidence == ""


def test_case_insensitive_and_plural():
    assert detect_newsletter("NEWSLETTERS")[0] is True


def test_evidence_is_capped():
    present, evidence = detect_newsletter("newsletter " + "x" * 500)
    assert present is True
    assert len(evidence) <= 160


def test_newsletter_is_not_an_editorial_url():
    """Guards Task 5's fix: /newsletter must not count as an editorial section,
    while still being detected as a newsletter channel."""
    html = '<a href="/newsletter">Newsletter</a>'
    assert find_editorial_urls(html, "https://acme.com") == []
    assert detect_newsletter(html)[0] is True
