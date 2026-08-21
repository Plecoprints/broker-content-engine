from bce.detectors import detect_newsletter, find_editorial_urls


def test_detects_newsletter_signup():
    present, evidence = detect_newsletter("Sign up for our newsletter below.")
    assert present is True
    assert "newsletter" in evidence.lower()


def test_detects_subscribe_wording_with_email_co_signal():
    """'subscribe' qualifies when an email co-signal backs it up.

    Changed from asserting on bare "Subscribe to receive new listings.": since
    a newsletter alone qualifies a broker (spec §4 v0.5), the bare word is too
    weak — see the non-match tests below.
    """
    present, _ = detect_newsletter(
        '<p>Subscribe to receive new listings.</p><input type="email" name="e">'
    )
    assert present is True
    assert detect_newsletter("Subscribe to our email updates.")[0] is True


def test_javascript_subscribe_does_not_count():
    """`store.subscribe(fn)` in an inline script is not a newsletter (C1b)."""
    html = (
        "<html><body><h1>Yachts</h1>"
        "<script>var store={};store.subscribe(function(s){});"
        "obs.subscribe(x);</script></body></html>"
    )
    present, evidence = detect_newsletter(html)
    assert present is False
    assert evidence == ""


def test_youtube_subscribe_does_not_count():
    present, _ = detect_newsletter(
        '<a href="https://youtube.com/c/acme">Subscribe to our YouTube channel</a>'
    )
    assert present is False


def test_unsubscribe_footer_does_not_count():
    """Regression guard for the rewritten matcher: a footer "Unsubscribe from
    this list" must not set has_newsletter."""
    assert detect_newsletter("<footer>Unsubscribe from this list</footer>")[0] is False


def test_privacy_policy_boilerplate_does_not_count():
    present, _ = detect_newsletter(
        "<p>You may subscribe or withdraw consent at any time under GDPR.</p>"
    )
    assert present is False


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
