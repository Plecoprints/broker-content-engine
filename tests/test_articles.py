from bce.articles import (
    MAX_ARTICLES_PER_BROKER,
    MAX_INDEX_PAGES,
    MAX_POST_CANDIDATES,
    MIN_ARTICLE_CHARS,
    collect_articles,
    collect_broker_articles,
    extract_article_text,
)
from bce.detectors import looks_like_index

ARTICLE_HTML = """
<html><body>
  <nav><a href="/blog">Blog</a><a href="/contact">Contact</a></nav>
  <article>
    <h1>Choosing a Mediterranean Catamaran</h1>
    <p>Beam matters more than length when you are berthing in Porto Cervo in August.
       A wide platform buys you deck space and steadiness at anchor.</p>
    <p>Draft is the other constraint nobody mentions until it is too late.</p>
  </article>
  <footer>Copyright 2026. Subscribe to our newsletter.</footer>
</body></html>
"""


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.pages.get(url)

    def robots_allows(self, url):
        return True


def test_extract_drops_nav_and_footer_boilerplate():
    text = extract_article_text(ARTICLE_HTML)
    assert "Beam matters more than length" in text
    assert "Contact" not in text
    assert "Subscribe to our newsletter" not in text


def test_extract_returns_none_for_a_page_with_no_body():
    assert extract_article_text("<html><body></body></html>") is None


def test_extract_does_not_raise_on_garbage():
    assert extract_article_text("<<<not really html") in (None, "")


def test_collect_articles_gathers_text_from_each_url():
    pages = {"https://a.invalid/1": ARTICLE_HTML, "https://a.invalid/2": ARTICLE_HTML}
    got = collect_articles(FakeFetcher(pages), list(pages))
    assert len(got) == 2
    assert all("Beam matters" in t for t in got)


def test_collect_articles_skips_unfetchable_and_empty_pages():
    pages = {"https://a.invalid/1": None, "https://a.invalid/2": ARTICLE_HTML}
    got = collect_articles(FakeFetcher(pages), list(pages))
    assert len(got) == 1


def test_collect_articles_is_bounded():
    urls = [f"https://a.invalid/{i}" for i in range(12)]
    fetcher = FakeFetcher({u: ARTICLE_HTML for u in urls})
    got = collect_articles(fetcher, urls)
    assert len(got) == MAX_ARTICLES_PER_BROKER
    assert len(fetcher.calls) == MAX_ARTICLES_PER_BROKER


def test_collect_articles_handles_no_urls():
    assert collect_articles(FakeFetcher({}), []) == []


# --- C1: the two-level walk --------------------------------------------------

LONG_BODY = "".join(
    f"<p>Paragraph {i} carries enough real prose about beam, draft, galley "
    f"layout and resale value that trafilatura keeps it and the extracted "
    f"text comfortably clears the plausibility floor for one article.</p>"
    for i in range(5)
)


def _post_page(title):
    return f"<html><body><article><h1>{title}</h1>{LONG_BODY}</article></body></html>"


def _index_page(paths):
    cards = "".join(f'<div><a href="{p}">{p}</a><p>Teaser.</p></div>' for p in paths)
    return (
        "<html><body><nav><a href='/about'>About</a></nav>"
        f"<main><h1>Journal</h1>{cards}</main></body></html>"
    )


def test_collect_broker_articles_follows_an_index_to_its_posts():
    paths = ["/journal/a", "/journal/b", "/journal/c"]
    pages = {"https://a.invalid/journal": _index_page(paths)}
    pages.update({f"https://a.invalid{p}": _post_page(p) for p in paths})
    fetcher = FakeFetcher(pages)

    got = collect_broker_articles(fetcher, ["https://a.invalid/journal"])
    assert len(got) == 3
    assert all(len(t) >= MIN_ARTICLE_CHARS for t in got)
    assert "Teaser." not in " ".join(got)


def test_collect_broker_articles_follows_flat_permalinks():
    paths = ["/why-beam-matters", "/draft-matters", "/galley-layouts"]
    pages = {"https://a.invalid/journal": _index_page(paths)}
    pages.update({f"https://a.invalid{p}": _post_page(p) for p in paths})
    fetcher = FakeFetcher(pages)

    got = collect_broker_articles(fetcher, ["https://a.invalid/journal"])
    assert len(got) == 3
    for path in paths:
        assert f"https://a.invalid{path}" in fetcher.calls


def test_collect_broker_articles_keeps_an_editorial_page_that_is_itself_an_article():
    pages = {"https://a.invalid/journal": _post_page("One long journal page")}
    fetcher = FakeFetcher(pages)
    got = collect_broker_articles(fetcher, ["https://a.invalid/journal"])
    assert len(got) == 1
    # No second hop needed, so nothing beyond the editorial URL was fetched.
    assert fetcher.calls == ["https://a.invalid/journal"]


def test_collect_broker_articles_discards_a_thin_index():
    pages = {"https://a.invalid/journal": _index_page([])}
    assert collect_broker_articles(FakeFetcher(pages), ["https://a.invalid/journal"]) == []


def test_collect_broker_articles_discards_thin_posts():
    pages = {
        "https://a.invalid/journal": _index_page(["/journal/stub"]),
        "https://a.invalid/journal/stub":
            "<html><body><article><p>Coming soon.</p></article></body></html>",
    }
    assert collect_broker_articles(FakeFetcher(pages), ["https://a.invalid/journal"]) == []


def test_collect_broker_articles_stops_at_the_article_bound_before_fetching():
    paths = [f"/journal/{i}" for i in range(12)]
    pages = {"https://a.invalid/journal": _index_page(paths)}
    pages.update({f"https://a.invalid{p}": _post_page(p) for p in paths})
    fetcher = FakeFetcher(pages)

    got = collect_broker_articles(fetcher, ["https://a.invalid/journal"])
    assert len(got) == MAX_ARTICLES_PER_BROKER
    # One index fetch plus exactly MAX_ARTICLES_PER_BROKER post fetches: the
    # bound is checked before each fetch, never after (spec §10.2).
    assert len(fetcher.calls) == 1 + MAX_ARTICLES_PER_BROKER


def test_collect_broker_articles_caps_wasted_post_fetches():
    """Every post is a stub, so nothing is collected and the bound must be the
    candidate budget rather than the article count."""
    paths = [f"/journal/{i}" for i in range(50)]
    pages = {"https://a.invalid/journal": _index_page(paths)}
    pages.update({
        f"https://a.invalid{p}": "<html><body><article><p>Soon.</p></article></body></html>"
        for p in paths
    })
    fetcher = FakeFetcher(pages)

    assert collect_broker_articles(fetcher, ["https://a.invalid/journal"]) == []
    assert len(fetcher.calls) == 1 + MAX_POST_CANDIDATES


def test_a_busy_index_does_not_qualify_as_an_article_on_length_alone():
    """Forty teaser cards clear any character floor while being pure card titles.

    The card paths are **root-level slugs**, not `/journal/<n>`: with deeper paths
    this test would pass on the depth rule alone and prove nothing about
    structure. Flat permalinks are invisible to path shape, so the only thing
    keeping this index from being profiled as an article is link density.
    """
    paths = [f"/post-{i}" for i in range(40)]
    index = _index_page(paths)
    assert len(extract_article_text(index)) > MIN_ARTICLE_CHARS
    assert looks_like_index(index, "https://a.invalid/journal") is True

    pages = {"https://a.invalid/journal": index}
    pages.update({
        f"https://a.invalid{p}": "<html><body><article><p>Soon.</p></article></body></html>"
        for p in paths
    })
    assert collect_broker_articles(FakeFetcher(pages), ["https://a.invalid/journal"]) == []


def test_collect_broker_articles_bounds_the_index_pages_it_follows():
    urls = [f"https://a.invalid/news{i}" for i in range(9)]
    fetcher = FakeFetcher({u: _index_page([]) for u in urls})
    assert collect_broker_articles(fetcher, urls) == []
    assert len(fetcher.calls) == MAX_INDEX_PAGES


def test_collect_broker_articles_does_not_refetch_a_post_two_indexes_share():
    paths = ["/journal/a", "/journal/b"]
    pages = {
        "https://a.invalid/journal": _index_page(paths),
        "https://a.invalid/news": _index_page(paths),
    }
    pages.update({f"https://a.invalid{p}": _post_page(p) for p in paths})
    fetcher = FakeFetcher(pages)

    got = collect_broker_articles(
        fetcher, ["https://a.invalid/journal", "https://a.invalid/news"]
    )
    assert len(got) == 2
    assert len(fetcher.calls) == len(set(fetcher.calls))


def test_collect_broker_articles_skips_an_unfetchable_index():
    assert collect_broker_articles(FakeFetcher({}), ["https://a.invalid/journal"]) == []


def test_collect_broker_articles_handles_no_editorial_urls():
    assert collect_broker_articles(FakeFetcher({}), []) == []
