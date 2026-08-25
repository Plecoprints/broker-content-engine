"""Deterministic style statistics (spec §5 Stage 3).

Pure functions over text. The LLM handles judgement; this handles counting, so
the countable half of a voice profile is reproducible and testable offline.
"""
import json
import re
import statistics

#: Sentence end: .!? followed by whitespace and a capital or quote. Requiring the
#: capital is what keeps "approx. 24.5 m" and "$1.5m" from splitting a sentence.
_SENTENCE_END = re.compile(r"[.!?]+\s+(?=[\"'(]?[A-Z])")
_WORD = re.compile(r"\b[\w'-]+\b")
_PARA_SPLIT = re.compile(r"\n\s*\n+")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text.strip()) if s.strip()]


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def avg_sentence_length(texts: list[str]) -> float:
    lengths = [
        len(_words(sentence))
        for text in texts
        for sentence in _sentences(text)
        if _words(sentence)
    ]
    if not lengths:
        return 0.0
    return round(statistics.fmean(lengths), 1)


def typical_word_count(texts: list[str]) -> int:
    counts = [len(_words(t)) for t in texts if _words(t)]
    if not counts:
        return 0
    return round(statistics.median(counts))


def structure_pattern(texts: list[str]) -> str:
    """Article shape as a JSON object in a TEXT column (spec §10.3 *Tailored*).

    JSON, not prose: Stage 4 has to *score* structure match against this, which
    means comparing numbers. Its siblings in the same INSERT already store JSON
    (`vocabulary_markers`, `themes`, `sample_quotes`), so this is the column's
    house format rather than a new one — no schema change.

    Both values are rounded here rather than at render time, so the stored
    statistic is the same integer every reader sees, and matches how
    `typical_word_count` rounds its median.

    The no-input case is `{"paragraphs_per_article": null, "words_per_paragraph":
    null}` — still parseable JSON, and distinguishable from real data by the
    nulls rather than by an in-band `"unknown"` sentinel a parser would have to
    special-case.
    """
    # Compute per-article statistics, skipping texts with zero paragraphs
    per_text_stats = []
    for text in texts:
        paragraphs = [
            p for p in _PARA_SPLIT.split(text.strip()) if p.strip()
        ]
        if paragraphs:  # Only include texts with at least one paragraph
            num_paras = len(paragraphs)
            words_per_para = [len(_words(p)) for p in paragraphs]
            per_text_stats.append((num_paras, statistics.fmean(words_per_para)))

    if not per_text_stats:
        return json.dumps({"paragraphs_per_article": None, "words_per_paragraph": None})

    # Compute mean paragraphs per article and mean words per paragraph
    mean_paras = statistics.fmean([n for n, _ in per_text_stats])
    mean_words = statistics.fmean([w for _, w in per_text_stats])

    return json.dumps({
        "paragraphs_per_article": round(mean_paras),
        "words_per_paragraph": round(mean_words),
    })


MAX_QUOTE_CHARS = 200
MAX_QUOTES = 5
MAX_RETAINED_FRACTION = 0.25


def select_quotes(texts: list[str]) -> list[str]:
    """Up to MAX_QUOTES capped sentences, chosen as representative of register.

    Spec §10.3: derived features and short illustrative quotes only. This is the
    only place source prose is retained, and it is bounded three times — by count,
    by length per quote, and by total fraction of source.

    Returns sentences closest to the mean length, up to MAX_QUOTES. Each sentence
    is truncated to MAX_QUOTE_CHARS. Total retained characters must not exceed
    MAX_RETAINED_FRACTION (25%) of the combined source length. If even a single
    quote exceeds that threshold, returns empty list rather than storing an
    oversized excerpt.
    """
    sentences = [s.strip() for text in texts for s in _sentences(text) if s.strip()]
    if not sentences:
        return []

    # Calculate combined source length for proportional cap
    source_length = sum(len(text) for text in texts)
    max_retained = int(source_length * MAX_RETAINED_FRACTION)

    mean = statistics.fmean([len(_words(s)) for s in sentences])
    ranked = sorted(sentences, key=lambda s: abs(len(_words(s)) - mean))

    # Truncate each quote and check proportional constraint
    capped_quotes = [s[:MAX_QUOTE_CHARS] for s in ranked[:MAX_QUOTES]]

    # Check if any single quote exceeds the proportional limit
    if any(len(q) > max_retained for q in capped_quotes):
        return []

    # Retain quotes in ranking order until total would exceed proportional cap
    result = []
    total_retained = 0
    for quote in capped_quotes:
        if total_retained + len(quote) <= max_retained:
            result.append(quote)
            total_retained += len(quote)

    return result
