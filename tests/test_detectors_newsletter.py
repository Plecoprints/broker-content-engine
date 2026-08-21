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


# --- Residual B: the email co-signal must be local to the match --------------

_FILLER = "<p>" + ("Lorem ipsum dolor sit amet. " * 12) + "</p>"


def test_youtube_subscribe_with_unrelated_email_input_elsewhere_does_not_count():
    """A social 'Subscribe' link must not be backed by a contact-form email
    input elsewhere on the page — the false positive Residual B calls out."""
    html = (
        "<html><body>"
        "<footer><a href='https://youtube.com/c/acme'>Subscribe to our "
        "YouTube channel</a></footer>"
        f"{_FILLER}"
        "<section class='contact'><form>"
        "<input type='email' name='contact_email'>"
        "</form></section>"
        "</body></html>"
    )
    assert detect_newsletter(html)[0] is False


def test_cookie_banner_subscribe_wording_with_unrelated_email_input_does_not_count():
    """A cookie/privacy banner mentioning subscribe/unsubscribe must not be
    backed by an email input elsewhere on the page."""
    html = (
        "<html><body>"
        "<div class='cookie-banner'>You may subscribe or unsubscribe from "
        "our communications at any time.</div>"
        f"{_FILLER}"
        "<section class='contact'><form>"
        "<input type='email' name='contact_email'>"
        "</form></section>"
        "</body></html>"
    )
    assert detect_newsletter(html)[0] is False


def test_youtube_subscribe_and_email_input_under_shared_section_ancestor_does_not_count():
    """Regression for the reviewer's finding: a broad `<section>` wrapping
    both an unrelated footer 'Subscribe' link and a distant, unrelated email
    input must not count merely because they share that outer `<section>` —
    only a shared `<form>` subtree does. A lazy `<(form|section)\\b.*?</\\1>`
    regex would match this entire `<section>` as one "block" and treat the
    unrelated input as local evidence, reopening Residual B."""
    html = (
        "<html><body>"
        "<section class='page'>"
        "<footer><a href='https://youtube.com/c/acme'>Subscribe to our "
        "YouTube channel</a></footer>"
        f"{_FILLER}"
        "<div class='contact'><input type='email' name='contact_email'></div>"
        "</section>"
        "</body></html>"
    )
    assert detect_newsletter(html)[0] is False


def test_cookie_banner_and_email_input_under_shared_div_ancestor_does_not_count():
    """Same shape as above with a shared `<div>` ancestor instead of
    `<section>`, and cookie/privacy banner wording instead of a social link."""
    html = (
        "<html><body>"
        "<div class='wrapper'>"
        "<div class='cookie-banner'>You may subscribe or unsubscribe from "
        "our communications at any time.</div>"
        f"{_FILLER}"
        "<div class='contact'><input type='email' name='contact_email'></div>"
        "</div>"
        "</body></html>"
    )
    assert detect_newsletter(html)[0] is False


def test_genuine_signup_block_with_email_input_in_same_form_counts():
    """A real signup block — subscribe wording and an email input sharing one
    <form> — still counts, even when they are farther apart than the bare
    proximity window."""
    html = (
        "<html><body>"
        "<section class='hero'><h1>Yachts</h1></section>"
        "<form class='signup'>"
        "<p>Subscribe to stay in the loop.</p>"
        f"{_FILLER}"
        "<input type='email' name='signup_email'>"
        "</form>"
        "</body></html>"
    )
    present, evidence = detect_newsletter(html)
    assert present is True
    assert "subscrib" in evidence.lower()


def test_self_sufficient_hints_still_work_without_any_email_input():
    """The explicit newsletter/mailing-list phrases keep qualifying on their
    own, unaffected by the co-signal locality fix."""
    assert detect_newsletter("<p>Join our mailing list.</p>")[0] is True
    assert detect_newsletter("<p>Sign up for email updates.</p>")[0] is True
    assert detect_newsletter("<p>Our email list is the best way to follow "
                              "us.</p>")[0] is True
    assert detect_newsletter("<p>Read our newsletter.</p>")[0] is True


def test_newsletter_is_not_an_editorial_url():
    """Guards Task 5's fix: /newsletter must not count as an editorial section,
    while still being detected as a newsletter channel."""
    html = '<a href="/newsletter">Newsletter</a>'
    assert find_editorial_urls(html, "https://acme.com") == []
    assert detect_newsletter(html)[0] is True
