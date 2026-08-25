"""Stage 3 — gather article text from a broker's editorial pages (spec §5).

Extraction only. Nothing here stores text; the caller derives features from what
this returns and discards the text (spec §10.3).

**Two levels, not one.** `find_editorial_urls` returns *section* pages —
`/journal`, `/news`, `/blog`. Those are index pages, and trafilatura on an index
yields teaser fragments rather than an article body. `collect_broker_articles`
therefore follows each index through to the posts behind it, and falls back to
the index itself only when that page is genuinely one long article. Every fetch
still goes through `Fetcher.get` (robots.txt, ≥2s per host — spec §10.2) and
every bound below is checked *before* a fetch, never after.
"""
import trafilatura

from bce.detectors import find_post_links

MAX_ARTICLES_PER_BROKER = 5

#: Editorial index pages followed per broker. `find_editorial_urls` can return a
#: dozen section links on a site that says "news" in every nav block; without
#: this the second hop would multiply out.
MAX_INDEX_PAGES = 3

#: Post pages fetched per broker across *all* indexes. Worst case is therefore
#: MAX_INDEX_PAGES + MAX_POST_CANDIDATES = 13 requests, ~26s at the §10.2 delay.
MAX_POST_CANDIDATES = 10

#: The least extracted prose that can plausibly be an article. Measured against
#: real pages: a journal *index* extracts to ~120 chars of teaser fragments, and
#: `style.select_quotes` cannot return anything at all below ~450 chars because
#: one truncated quote already breaches the 25% retention cap. 600 sits above
#: both, and far below the shortest real broker post (the suite's realistic
#: fixture extracts to ~1600). Below this the page is index chrome, not writing.
MIN_ARTICLE_CHARS = 600


def extract_article_text(html: str) -> str | None:
    """Boilerplate-free body text, or None when there is nothing to extract."""
    try:
        return trafilatura.extract(html)
    except Exception:
        return None


def _article_text(html: str | None) -> str | None:
    """Extracted text that is long enough to be an article, else None."""
    if html is None:
        return None
    text = extract_article_text(html)
    if text and len(text) >= MIN_ARTICLE_CHARS:
        return text
    return None


def collect_articles(fetcher, editorial_urls: list[str]) -> list[str]:
    """Up to MAX_ARTICLES_PER_BROKER article texts, skipping pages that yield none.

    The single-level primitive: fetch each URL, extract, keep whatever comes back.
    Stage 3 uses `collect_broker_articles` instead, which walks index → post.
    """
    articles: list[str] = []
    for url in editorial_urls:
        if len(articles) >= MAX_ARTICLES_PER_BROKER:
            break
        html = fetcher.get(url)
        if html is None:
            continue
        text = extract_article_text(html)
        if text:
            articles.append(text)
    return articles


def collect_broker_articles(fetcher, editorial_urls: list[str]) -> list[str]:
    """Article bodies for one broker, following editorial indexes to their posts.

    For each editorial section URL (up to MAX_INDEX_PAGES): fetch it once, and
    prefer the posts linked from it, up to a shared MAX_POST_CANDIDATES budget.
    Only when the page links to no posts at all is the page's own text used —
    that is the "broker publishes one long journal page" case, and requiring the
    absence of post links is what keeps a *busy* index from qualifying as an
    article on length alone. A journal index with forty teaser cards clears any
    plausible character floor while being nothing but card titles.

    Pages yielding less than MIN_ARTICLE_CHARS of text are discarded rather than
    profiled: statistics derived from teaser fragments are confidently wrong, and
    Stage 4 conditions drafting on them (spec §5, §10.3).
    """
    articles: list[str] = []
    seen_posts: set[str] = set()
    posts_fetched = 0

    for index_url in editorial_urls[:MAX_INDEX_PAGES]:
        if len(articles) >= MAX_ARTICLES_PER_BROKER:
            break
        index_html = fetcher.get(index_url)
        if index_html is None:
            continue

        post_urls = find_post_links(index_html, index_url, exclude=editorial_urls)
        if not post_urls:
            direct = _article_text(index_html)
            if direct is not None:
                articles.append(direct)
            continue

        for post_url in post_urls:
            if len(articles) >= MAX_ARTICLES_PER_BROKER:
                break
            if posts_fetched >= MAX_POST_CANDIDATES:
                break
            if post_url in seen_posts:
                continue
            seen_posts.add(post_url)
            posts_fetched += 1
            text = _article_text(fetcher.get(post_url))
            if text is not None:
                articles.append(text)

    return articles
