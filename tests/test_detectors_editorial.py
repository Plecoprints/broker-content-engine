from bce.detectors import (
    MIN_INDEX_LINKS,
    detect_last_post_date,
    find_editorial_urls,
    find_post_links,
    looks_like_index,
)


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


# Regression tests: word-boundary matching to avoid false positives
def test_rejects_newsletter_signup():
    """'news' should not match inside 'newsletter' — requires word boundary."""
    html = '<a href="/newsletter">Newsletter</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


def test_handles_articles_of_association():
    """'article' + word boundary matches 'articles' in '/articles-of-association'."""
    html = '<a href="/articles-of-association">Articles of Association</a>'
    # '-' is non-word, so \barticles\b matches; articles + s is a bounded token.
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/articles-of-association"]


def test_matches_blog_in_path_with_dashes():
    """Dashes create word boundaries; '/blog-posts' should still match."""
    html = '<a href="/blog-posts">Posts</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/blog-posts"]


def test_case_insensitive_href():
    """Uppercase href is matched case-insensitively."""
    html = '<a href="/BLOG">Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == ["https://acme.com/BLOG"]


def test_rejects_protocol_relative_offsite():
    """Protocol-relative URLs to other hosts are rejected."""
    html = '<a href="//other.com/blog">Blog</a>'
    assert find_editorial_urls(html, "https://acme.com") == []


# --- I6: editorial recency (spec §4 — updated within the last 12 months) -----

def test_detects_date_from_time_element():
    html = '<html><body><article><time datetime="2026-07-15">July</time></article></body></html>'
    assert detect_last_post_date(html) == "2026-07-15"


def test_detects_date_from_article_metadata():
    html = (
        '<html><head><meta property="article:published_time" '
        'content="2019-03-02T10:00:00Z"></head><body><h1>Old post</h1></body></html>'
    )
    assert detect_last_post_date(html) == "2019-03-02"


def test_returns_none_when_no_date_is_declared():
    assert detect_last_post_date("<html><body><p>No dates here.</p></body></html>") is None


def test_returns_none_on_empty_or_junk_input():
    assert detect_last_post_date("") is None
    assert detect_last_post_date("\x00\x01 not html at all") is None


# --- C1: the second hop, index -> posts --------------------------------------

INDEX = "https://acme.com/journal"


def test_finds_posts_deeper_than_the_index():
    html = (
        '<a href="/journal/why-beam-matters">Why beam matters</a>'
        '<a href="/journal/draft-depth">Draft depth</a>'
    )
    assert find_post_links(html, INDEX) == [
        "https://acme.com/journal/why-beam-matters",
        "https://acme.com/journal/draft-depth",
    ]


def test_ignores_nav_links():
    """Nav is excluded structurally, by region, not by path depth.

    This fixture used to be three bare anchors and relied on `/about` not being
    deeper than `/journal`. Depth was standing in for "this is chrome", and that
    proxy is exactly what a flat-permalink index defeats — `/why-beam-matters` is
    not deeper than `/journal` either. The markup now says what it means.
    """
    html = (
        "<nav><a href='/about'>About</a><a href='/contact'>Contact</a>"
        "<a href='/'>Home</a></nav><main><p>Journal</p></main>"
    )
    assert find_post_links(html, INDEX) == []


def test_below_the_index_threshold_the_depth_rule_still_applies():
    """Two in-body links is not a listing, so a long-form page that links to
    /contact and /about is not mistaken for one."""
    html = "<main><p>A post that links to <a href='/about'>about</a> and " \
           "<a href='/contact'>contact</a>.</p></main>"
    assert find_post_links(html, INDEX) == []
    assert looks_like_index(html, INDEX) is False


def test_accepts_a_dated_path_even_at_the_same_depth():
    html = '<a href="/2026/berthing-in-august">Berthing</a>'
    assert find_post_links(html, INDEX) == ["https://acme.com/2026/berthing-in-august"]


def test_excludes_the_index_itself_and_other_editorial_sections():
    html = (
        '<a href="/journal">Journal</a>'
        '<a href="/journal/">Journal again</a>'
        '<a href="/news">News</a>'
        '<a href="/journal/a-real-post">A real post</a>'
    )
    got = find_post_links(html, INDEX, exclude=["https://acme.com/journal",
                                                "https://acme.com/news"])
    assert got == ["https://acme.com/journal/a-real-post"]


def test_ignores_offsite_and_non_page_links():
    html = (
        '<a href="https://other.com/journal/post">Offsite</a>'
        '<a href="mailto:hi@acme.com">Email</a>'
        '<a href="tel:+123">Call</a>'
        '<a href="#top">Top</a>'
        '<a href="/journal/keeper">Keeper</a>'
    )
    assert find_post_links(html, INDEX) == ["https://acme.com/journal/keeper"]


def test_deduplicates_and_drops_fragments():
    html = (
        '<a href="/journal/post-a">A</a>'
        '<a href="/journal/post-a#comments">A again</a>'
        '<a href="/journal/post-a">A once more</a>'
    )
    assert find_post_links(html, INDEX) == ["https://acme.com/journal/post-a"]


def test_handles_empty_html():
    assert find_post_links("", INDEX) == []
    assert looks_like_index("", INDEX) is False


# --- Blocker: flat /%postname%/ permalinks -----------------------------------

FLAT_INDEX = (
    "<nav><a href='/about'>About</a></nav>"
    "<main><h1>Journal</h1>"
    "<div><a href='/why-beam-matters'>Why beam matters</a><p>Teaser.</p></div>"
    "<div><a href='/draft-and-the-harbourmaster'>Draft</a><p>Teaser.</p></div>"
    "<div><a href='/galley-layouts-that-sell'>Galley</a><p>Teaser.</p></div>"
    "</main>"
)


def test_finds_flat_permalink_posts_that_are_neither_deeper_nor_dated():
    """WordPress's default /%postname%/: /journal links to /why-beam-matters."""
    got = find_post_links(FLAT_INDEX, INDEX)
    assert got == [
        "https://acme.com/why-beam-matters",
        "https://acme.com/draft-and-the-harbourmaster",
        "https://acme.com/galley-layouts-that-sell",
    ]
    # None of them would survive the path-shape rule on its own.
    for url in got:
        assert len(url.rstrip("/").split("/")) == 4  # https://acme.com/<slug>


def test_a_flat_index_is_recognised_structurally():
    assert looks_like_index(FLAT_INDEX, INDEX) is True


def test_index_detection_ignores_chrome_and_offsite_links():
    """Density is counted in the content region only, so a big nav is not a
    listing and a page of outbound links is not one either."""
    chrome = "<nav>" + "".join(
        f"<a href='/page{i}'>Page {i}</a>" for i in range(10)
    ) + "</nav><main><p>One long journal entry.</p></main>"
    assert looks_like_index(chrome, INDEX) is False

    offsite = "<main>" + "".join(
        f"<a href='https://other.com/{i}'>Partner {i}</a>" for i in range(10)
    ) + "</main>"
    assert looks_like_index(offsite, INDEX) is False


def test_editorial_sections_do_not_count_toward_index_density():
    html = "<main>" + "".join(
        f"<a href='/section{i}'>Section {i}</a>" for i in range(3)
    ) + "</main>"
    sections = [f"https://acme.com/section{i}" for i in range(3)]
    assert looks_like_index(html, INDEX, exclude=sections) is False
    assert find_post_links(html, INDEX, exclude=sections) == []


def test_index_threshold_is_exact():
    def flat(n):
        return "<main>" + "".join(
            f"<a href='/slug-{i}'>Post {i}</a>" for i in range(n)
        ) + "</main>"

    assert looks_like_index(flat(MIN_INDEX_LINKS - 1), INDEX) is False
    assert looks_like_index(flat(MIN_INDEX_LINKS), INDEX) is True
    # Below the threshold the flat links are not posts by the depth rule either.
    assert find_post_links(flat(MIN_INDEX_LINKS - 1), INDEX) == []
    assert len(find_post_links(flat(MIN_INDEX_LINKS), INDEX)) == MIN_INDEX_LINKS
