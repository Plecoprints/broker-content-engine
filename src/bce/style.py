"""Deterministic style statistics (spec §5 Stage 3).

Pure functions over text. The LLM handles judgement; this handles counting, so
the countable half of a voice profile is reproducible and testable offline.
"""
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
        return "unknown"

    # Compute mean paragraphs per article and mean words per paragraph
    mean_paras = statistics.fmean([n for n, _ in per_text_stats])
    mean_words = statistics.fmean([w for _, w in per_text_stats])

    return f"{round(mean_paras)} paragraphs/article, {round(mean_words)} words/para"


MAX_QUOTE_CHARS = 200
MAX_QUOTES = 5


def select_quotes(texts: list[str]) -> list[str]:
    """Up to MAX_QUOTES capped sentences, chosen as representative of register.

    Spec §10.3: derived features and short illustrative quotes only. This is the
    only place source prose is retained, and it is bounded twice — by count and
    by length.

    Returns sentences closest to the mean length, up to MAX_QUOTES. Each sentence
    is truncated to MAX_QUOTE_CHARS to ensure stored quotes never exceed the
    privacy bound.
    """
    sentences = [s.strip() for text in texts for s in _sentences(text) if s.strip()]
    if not sentences:
        return []

    mean = statistics.fmean([len(_words(s)) for s in sentences])
    ranked = sorted(sentences, key=lambda s: abs(len(_words(s)) - mean))
    return [s[:MAX_QUOTE_CHARS] for s in ranked[:MAX_QUOTES]]
