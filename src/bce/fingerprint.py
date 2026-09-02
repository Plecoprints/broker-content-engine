"""Shingle fingerprints for the Original gate (spec §10.3 Gate 3).

**The contradiction this resolves.** Spec §10.3 requires an *Original*
check -- near-duplication against the broker's own already-published prose,
so the engine never hands a broker back a rewrite of something they already
ran. But the same section also requires voice profiles to store "derived
features and short quotes, **never full article text**" -- and
`bce.articles.collect_broker_articles` fetches a broker's prose during
profiling and deliberately discards it once features are derived (spec:
"Extraction only. Nothing here stores text"). Taken together, the Original
gate has nothing to compare a draft against.

The resolution: store **shingle hashes, not prose**. A shingle is an
overlapping run of `SHINGLE_SIZE` consecutive words; `shingle_hashes` reduces
each one to an opaque fixed-size integer via a cryptographic hash. The
resulting set can be compared for overlap (this module's `containment`), but
no hash in it can be turned back into the words that produced it. This
satisfies "never full article text" literally -- the `source_fingerprint`
table (see `bce.db`) has no text column at all, only `broker_id` and
`shingle_hash` -- while still making the Original gate real rather than a
check with nothing to check against.

**Why n=6.** Near-duplicate detection conventionally shingles at n=5-8
words: short enough that a real match is still findable in a short piece (a
100-200 word newsletter blurb, spec §5 Stage 4's short format, yields dozens
of shingles even at the top of that range), long enough that a 6-word run
recurring by chance -- rather than because the same sentence was reused --
is vanishingly unlikely in ordinary English prose. 6 sits in the middle of
that range with no format-specific reason to prefer either edge.

**Why hashed with `hashlib`, not Python's built-in `hash()`.** `hash()` on
strings is salted per-process (`PYTHONHASHSEED`) unless explicitly disabled,
so the same shingle would hash differently across two runs of the pipeline
-- silently breaking every comparison against fingerprints written by an
earlier process. `hashlib.blake2b` is deterministic across processes and
machines, which is what makes a fingerprint stored today comparable against
a draft generated next quarter.
"""
import hashlib
import re

#: See module docstring "Why n=6".
SHINGLE_SIZE = 6

_WORD = re.compile(r"[\w'-]+")


def _words(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def _hash_shingle(words: tuple[str, ...]) -> int:
    """One shingle (already-lowercased words) to a deterministic 8-byte int.

    8 bytes (64 bits) keeps stored rows small -- this table can hold
    thousands of rows per broker -- while collision risk stays negligible
    at the corpus sizes this system runs at (spec §6: 50 brokers).

    Signed, not unsigned: SQLite's `INTEGER` column is a signed 64-bit
    value, and roughly half of all unsigned 64-bit digests exceed its
    range (`OverflowError: Python int too large to convert to SQLite
    INTEGER`) -- caught by this module's own tests attempting to persist a
    hash. `int.from_bytes(..., signed=True)` maps the same 8 bytes into
    SQLite's actual range instead of Python's unbounded one; it is still a
    deterministic, uniformly distributed function of the shingle, just not
    the same numeric convention as an unsigned hash would use.
    """
    digest = hashlib.blake2b(" ".join(words).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def shingle_hashes(text: str | None, n: int = SHINGLE_SIZE) -> set[int]:
    """The set of `n`-word shingle hashes in `text`.

    Fewer than `n` words yields the empty set -- there is no complete
    shingle to hash, not an error. Case- and whitespace-insensitive: words
    are lowercased and re-tokenized before shingling, so formatting
    differences between the stored source and a freshly generated draft
    never cost a match that content identity would otherwise find.
    """
    words = _words(text)
    if len(words) < n:
        return set()
    return {
        _hash_shingle(tuple(words[i:i + n]))
        for i in range(len(words) - n + 1)
    }


def containment(draft_hashes: set[int], source_hashes: set[int]) -> float:
    """The fraction of `draft_hashes` also present in `source_hashes`.

    Containment, not Jaccard: `source_hashes` is a broker's *entire*
    fingerprinted corpus (potentially many articles), while `draft_hashes`
    is one draft. Jaccard divides by the size of the *union*, so it would be
    crushed toward zero by that size mismatch even when the draft is a
    near-total rewrite of one source article -- exactly the case this gate
    exists to catch. Containment asks the right question instead: of this
    draft's shingles, how many already exist somewhere in what this broker
    has published. Returns 0.0 (not a `ZeroDivisionError`) when either set
    is empty -- an empty draft or an unfingerprinted broker has nothing to
    measure overlap against.
    """
    if not draft_hashes or not source_hashes:
        return 0.0
    return len(draft_hashes & source_hashes) / len(draft_hashes)
