from bce.detectors import find_editorial_urls


def test_finds_blog_link_and_absolutizes():
    html = '<a href="/blog">Our Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/blog"]


def test_matches_anchor_text_when_href_is_opaque():
    html = '<a href="/p/12">Latest News</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/p/12"]


def test_ignores_offsite_links():
    html = '<a href="https://other.com/blog">Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


def test_ignores_non_editorial_links():
    html = '<a href="/contact">Contact</a><a href="/fleet">Our Fleet</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


def test_deduplicates_preserving_order():
    html = '<a href="/journal">Journal</a><a href="/news">News</a><a href="/journal">J</a>'
    assert find_editorial_urls(html, "https://acme.com") == [
        "https://acme.com/journal",
        "https://acme.com/news",
    ]


def test_handles_absolute_same_host():
    html = '<a href="https://acme.com/insights">Insights</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/insights"]
