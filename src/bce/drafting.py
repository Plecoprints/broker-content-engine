"""Stage 4/5 orchestrator — angles to persisted dual-format drafts (spec §5).

`voice_profile` stores four columns as JSON *strings*
(`structure_pattern`, `vocabulary_markers`, `themes`, `sample_quotes`) --
see `profile.profile_broker`, which is what writes them that way. Both
`angles.AngleClient.propose` and `draft.DraftClient.write_long` /
`write_short` expect the *parsed* shape: a dict for `structure_pattern`,
lists for the other three. Nothing upstream of this module deserializes
them, so `_load_profile` below is the one place that does -- passing a raw
`sqlite3.Row` through would not raise (the argument types still "match"),
it would just condition every draft on JSON punctuation instead of the
broker's actual voice. Mirrors `web.app._loads`: tolerate NULL and
malformed JSON, never raise while drafting.
"""
import json
import sqlite3
from dataclasses import dataclass

from bce.angles import best_angle


@dataclass(frozen=True)
class DraftResult:
    """Outcome of one `draft_for_broker` attempt.

    A NamedTuple's truthiness comes from tuple emptiness, not from any
    business meaning -- a non-empty tuple is always truthy, so a caller
    doing `if result is False` (or trusting `bool(result)` to reflect
    "did this write anything") would be silently wrong. That exact trap
    caught Stage 3 (see `profile.ProfileResult`); mirrored here with an
    explicit `__bool__` instead.

    `written` is true exactly when the long-form draft (and its angle) were
    persisted. `short_written` lets the caller distinguish "both formats
    landed" from "the long draft is good but condensation failed" -- the
    long row is kept either way (see `draft_for_broker`).
    """

    written: bool
    short_written: bool = False

    def __bool__(self) -> bool:
        return self.written


def _loads(value, default):
    """JSON columns may be NULL or malformed; never raise while drafting.

    Mirrors `bce.web.app._loads` -- the article text `voice_profile` was
    built from is untrusted third-party content, and a broker profiled
    during a transient failure can carry a row with unparseable columns.
    """
    if not value:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def _load_profile(row: sqlite3.Row) -> dict:
    """The stored `voice_profile` row, deserialized to what the LLM clients
    expect: `structure_pattern` a dict, `vocabulary_markers`/`themes`/
    `sample_quotes` lists -- never the raw JSON strings SQLite hands back.
    """
    return {
        "register": row["register"],
        "avg_sentence_len": row["avg_sentence_len"],
        "typical_word_count": row["typical_word_count"],
        "structure_pattern": _loads(row["structure_pattern"], {}),
        "vocabulary_markers": _loads(row["vocabulary_markers"], []),
        "themes": _loads(row["themes"], []),
        "audience_signal": row["audience_signal"],
        "sample_quotes": _loads(row["sample_quotes"], []),
    }


def draft_for_broker(
    conn: sqlite3.Connection, broker_id: int, angle_client, draft_client
) -> DraftResult:
    """Propose angles, write both draft formats, and persist them.

    Loads the voice profile, proposes angles, picks the best one, writes the
    long-form draft and then condenses it to short-form, and persists one
    `angle` row plus one or two `draft` rows (`format='long'` always,
    `format='short'` when condensation succeeded).

    Nothing is written, and no client call is made, when: there is no voice
    profile row; the profile's judgement half never landed (classification
    failed, leaving `register`/`themes`/`audience_signal` NULL -- the same
    distinction `profile.ProfileResult.classified` makes, applied here so a
    broker with statistics-only "no profile" does not spend an angle call
    against nothing); angle proposal returns none; or the long draft comes
    back `None` (there is nothing to condense, so `write_short` is never
    called). A `None` short draft does not discard a good long draft --
    that row is still written, and `short_written` reports the failure.

    Both draft rows carry `status='pending_review'`; nothing here ever
    writes `'sent'` -- the schema requires a human in `reviewed_by` first.
    """
    broker = conn.execute(
        "SELECT name FROM broker WHERE id=?", (broker_id,)
    ).fetchone()
    profile_row = conn.execute(
        "SELECT * FROM voice_profile WHERE broker_id=?", (broker_id,)
    ).fetchone()
    if profile_row is None:
        return DraftResult(written=False)
    # Judgement half empty: classification failed and left register/themes/
    # audience_signal all NULL. Treated as no usable profile -- this belongs
    # here, not inside AngleClient, so the "no API call" contract holds for
    # this case too.
    if profile_row["register"] is None:
        return DraftResult(written=False)

    profile = _load_profile(profile_row)
    broker_name = broker["name"]

    angles = angle_client.propose(profile, broker_name)
    if not angles:
        return DraftResult(written=False)

    angle = best_angle(angles)
    long_body = draft_client.write_long(angle, profile, broker_name)
    if not long_body:
        return DraftResult(written=False)

    short_body = draft_client.write_short(long_body, profile)

    cursor = conn.execute(
        "INSERT INTO angle (broker_id, title, premise, audience_value, "
        "sunreef_relevance, score) VALUES (?,?,?,?,?,?)",
        (
            broker_id,
            angle.get("title"),
            angle.get("premise"),
            angle.get("audience_value"),
            angle.get("sunreef_relevance"),
            angle.get("score"),
        ),
    )
    angle_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
        "VALUES (?,?,?,?,?)",
        (angle_id, long_body, len(long_body.split()), "pending_review", "long"),
    )

    short_written = False
    if short_body:
        conn.execute(
            "INSERT INTO draft (angle_id, body_md, word_count, status, format) "
            "VALUES (?,?,?,?,?)",
            (angle_id, short_body, len(short_body.split()), "pending_review", "short"),
        )
        short_written = True

    conn.commit()
    return DraftResult(written=True, short_written=short_written)
