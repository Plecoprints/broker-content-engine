"""Stage 3 orchestrator — compose a voice profile and persist it (spec §5)."""
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from bce import style
from bce.articles import MIN_ARTICLE_CHARS, collect_broker_articles
from bce.detectors import find_editorial_urls

#: Corpus plausibility floor. A profile is only worth storing if the text behind
#: it could plausibly be a broker's writing. One article's worth (see
#: `articles.MIN_ARTICLE_CHARS`) is the minimum; below it the row would claim a
#: word count and a structure the broker never wrote, and Stage 4 drafts against
#: it (spec §5, §10.3 *Tailored*). Enforced here as well as in the collector so
#: no caller can persist a corpus this module has not vetted.
MIN_CORPUS_CHARS = MIN_ARTICLE_CHARS

#: Spec §10.3 caps what a broker's page may put into our store. `sample_quotes`
#: was already bounded three ways; the LLM half was not bounded at all. The
#: schema in `llm.PROFILE_SCHEMA` asks the model for these limits; this clamp is
#: what enforces them, because the article text is untrusted third-party content.
MAX_FIELD_CHARS = 120
MAX_LIST_ITEMS = 8


@dataclass(frozen=True)
class ProfileResult:
    """Outcome of one Stage 3 attempt.

    Truthy exactly when a row was written, so the existing `if ok:` /
    `'profiled' if ok else ...` contract is unchanged, while `classified`
    lets the caller distinguish a complete profile from one whose Claude call
    failed and left every judgement field NULL.
    """

    written: bool
    classified: bool = False

    def __bool__(self) -> bool:
        return self.written


def _clamp_text(value) -> str | None:
    """A bounded string, or None when the model returned nothing usable."""
    if not isinstance(value, str):
        return None
    trimmed = value.strip()[:MAX_FIELD_CHARS]
    return trimmed or None


def _clamp_list(value) -> list[str]:
    """At most MAX_LIST_ITEMS bounded strings; anything else becomes []."""
    if not isinstance(value, list):
        return []
    clamped = []
    for item in value[:MAX_LIST_ITEMS]:
        if isinstance(item, str):
            trimmed = item.strip()[:MAX_FIELD_CHARS]
            if trimmed:
                clamped.append(trimmed)
    return clamped


def profile_broker(
    conn: sqlite3.Connection, broker_id: int, fetcher, profile_client
) -> ProfileResult:
    """Fetch, analyse, and persist a broker's voice profile.

    Returns a truthy `ProfileResult` when a profile row was written, and a falsy
    one (without writing) when the homepage was unreachable or the article corpus
    was too thin to describe. No API call is made in either no-write case (spec:
    no articles means no API call).
    """
    row = conn.execute("SELECT domain FROM broker WHERE id=?", (broker_id,)).fetchone()
    url = f"https://{row['domain']}/"

    html = fetcher.get(url)
    if html is None:
        return ProfileResult(written=False)

    texts, paragraph_lists = collect_broker_articles(fetcher, find_editorial_urls(html, url))
    if sum(len(a) for a in texts) < MIN_CORPUS_CHARS:
        return ProfileResult(written=False)

    judgement = profile_client.classify(texts)
    if not isinstance(judgement, dict):
        judgement = {}

    register = _clamp_text(judgement.get("register"))
    audience_signal = _clamp_text(judgement.get("audience_signal"))
    vocabulary_markers = _clamp_list(judgement.get("vocabulary_markers"))
    themes = _clamp_list(judgement.get("themes"))

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
            register,
            style.avg_sentence_length(texts),
            style.typical_word_count(texts),
            style.structure_pattern(paragraph_lists),
            json.dumps(vocabulary_markers),
            json.dumps(themes),
            audience_signal,
            json.dumps(style.select_quotes(texts)),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return ProfileResult(written=True, classified=register is not None)
