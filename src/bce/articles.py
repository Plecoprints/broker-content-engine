"""Stage 3 — gather article text from a broker's editorial pages (spec §5).

Extraction only. Nothing here stores text; the caller derives features from what
this returns and discards the text (spec §10.3).
"""
import trafilatura

MAX_ARTICLES_PER_BROKER = 5


def extract_article_text(html: str) -> str | None:
    """Boilerplate-free body text, or None when there is nothing to extract."""
    try:
        return trafilatura.extract(html)
    except Exception:
        return None


def collect_articles(fetcher, editorial_urls: list[str]) -> list[str]:
    """Up to MAX_ARTICLES_PER_BROKER article texts, skipping pages that yield none."""
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
