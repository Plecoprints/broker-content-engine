"""Stage 3 orchestrator — compose a voice profile and persist it (spec §5)."""
import json
import sqlite3
from datetime import datetime, timezone

from bce import style
from bce.articles import collect_articles
from bce.detectors import find_editorial_urls


def profile_broker(conn: sqlite3.Connection, broker_id: int, fetcher, profile_client) -> bool:
    """Fetch, analyse, and persist a broker's voice profile.

    Returns True when a profile row was written, False (without writing) when
    the homepage was unreachable or no articles could be gathered. No API call
    is made in either no-write case (spec: no articles means no API call).
    """
    row = conn.execute("SELECT domain FROM broker WHERE id=?", (broker_id,)).fetchone()
    url = f"https://{row['domain']}/"

    html = fetcher.get(url)
    if html is None:
        return False

    articles = collect_articles(fetcher, find_editorial_urls(html, url))
    if not articles:
        return False

    judgement = profile_client.classify(articles)

    conn.execute(
        "INSERT INTO voice_profile (broker_id, register, avg_sentence_len, "
        "typical_word_count, structure_pattern, vocabulary_markers, themes, "
        "audience_signal, sample_quotes, analyzed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(broker_id) DO UPDATE SET "
        "register=excluded.register, avg_sentence_len=excluded.avg_sentence_len, "
        "typical_word_count=excluded.typical_word_count, "
        "structure_pattern=excluded.structure_pattern, "
        "vocabulary_markers=excluded.vocabulary_markers, themes=excluded.themes, "
        "audience_signal=excluded.audience_signal, "
        "sample_quotes=excluded.sample_quotes, analyzed_at=excluded.analyzed_at",
        (
            broker_id,
            judgement.get("register"),
            style.avg_sentence_length(articles),
            style.typical_word_count(articles),
            style.structure_pattern(articles),
            json.dumps(judgement.get("vocabulary_markers", [])),
            json.dumps(judgement.get("themes", [])),
            judgement.get("audience_signal"),
            json.dumps(style.select_quotes(articles)),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return True
