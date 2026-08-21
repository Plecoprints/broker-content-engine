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
    return int(statistics.median(counts))


def structure_pattern(texts: list[str]) -> str:
    paragraphs = [
        p for text in texts for p in _PARA_SPLIT.split(text.strip()) if p.strip()
    ]
    if not paragraphs:
        return "unknown"
    density = int(statistics.fmean([len(_words(p)) for p in paragraphs]))
    return f"{len(paragraphs)} paragraphs, {density} words/para"
