from bce.articles import MAX_ARTICLES_PER_BROKER, collect_articles, extract_article_text

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
