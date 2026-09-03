"""Stage 4/5 orchestrator — angles to persisted three-format drafts (spec §5).

`voice_profile` stores four columns as JSON *strings*
(`structure_pattern`, `vocabulary_markers`, `themes`, `sample_quotes`) --
see `profile.profile_broker`, which is what writes them that way. Both
`angles.AngleClient.propose` and `draft.DraftClient.write_long` /
`write_medium` / `write_short` expect the *parsed* shape: a dict for
`structure_pattern`, lists for the other three. Nothing upstream of this
module deserializes them, so `_load_profile` below is the one place that
does -- passing a raw `sqlite3.Row` through would not raise (the argument
types still "match"), it would just condition every draft on JSON
punctuation instead of the broker's actual voice. Mirrors `web.app._loads`:
tolerate NULL and malformed JSON, never raise while drafting.
"""
import json
import sqlite3
from dataclasses import dataclass

from bce import keywords as keyword_selection
from bce import originality
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

    `written` is true exactly when the long-form (pillar) draft (and its
    angle) were persisted. `medium_written` / `short_written` let the caller
    distinguish "all three formats landed" from "the long draft is good but
    one or both condensations failed" -- the long row is kept regardless, and
    medium and short are independent: one failing does not discard the other
    (see `draft_for_broker`).
    """

    written: bool
    medium_written: bool = False
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


def _persist_draft_keywords(conn: sqlite3.Connection, draft_id: int, selection: dict) -> None:
    """Write the `draft_keyword` rows for one already-inserted draft row, in
    the same (still-uncommitted) transaction as that INSERT.

    A draft whose keywords didn't save is worse than one with none, because
    the UI would then misreport what's baked in -- so this is called
    immediately after each draft INSERT, before `conn.commit()`, never as a
    separate follow-up write. `selection` is the shape
    `keywords.select_for_draft` returns; when nothing qualified, `primary` is
    None and `secondary` is empty, so this writes nothing at all -- the
    keyword panel is then expected to say so plainly (spec §5b/§9), not this
    function.
    """
    primary = (selection or {}).get("primary")
    if primary is not None:
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?,?,?)",
            (draft_id, primary["id"], "primary"),
        )
    for kw in (selection or {}).get("secondary") or []:
        conn.execute(
            "INSERT INTO draft_keyword (draft_id, keyword_id, role) VALUES (?,?,?)",
            (draft_id, kw["id"], "secondary"),
        )


def _insert_gated_draft(
    conn: sqlite3.Connection,
    *,
    angle_id: int,
    broker_id: int,
    body: str,
    fmt: str,
    profile: dict,
    embedding_client,
    keywords,
) -> int:
    """Run the three §10.3 gates for one draft, then persist it with their
    verdicts, and return the new draft's id.

    Gates run **before** the INSERT, never after. `originality.check_uniqueness`
    compares against every persisted draft in this format bucket, so a draft
    inserted first would find itself and score a cosine similarity of 1.0 --
    every draft would fail as a duplicate of itself.

    The row is written whatever the verdict, and the embedding is stored even
    when the draft is rejected. That is spec §10.3's requirement that "a draft
    rejected for similarity still counts as seen, so the system cannot
    oscillate between two near-identical angles" -- a rejected draft that
    vanished from the corpus would let the next run regenerate the same thing.
    A draft failing any blocking gate lands `status='rejected'` and so never
    reaches the review queue.
    """
    gates = originality.run_gates(
        conn,
        broker_id=broker_id,
        format=fmt,
        body=body,
        profile=profile,
        embedding_client=embedding_client,
    )
    cursor = conn.execute(
        "INSERT INTO draft (angle_id, body_md, word_count, status, format, "
        "passes_uniqueness, max_similarity, most_similar_draft_id, embedding, "
        "passes_tailored, tailored_score, passes_originality, "
        "originality_overlap, passes_no_product_claims, product_claims_found) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            angle_id,
            body,
            len(body.split()),
            "pending_review" if gates.passes else "rejected",
            fmt,
            int(gates.passes_uniqueness),
            gates.max_similarity,
            gates.most_similar_draft_id,
            json.dumps(gates.embedding) if gates.embedding is not None else None,
            int(gates.passes_tailored),
            gates.tailored_score,
            int(gates.passes_originality),
            gates.originality_overlap,
            int(gates.passes_no_product_claims),
            # Stored as JSON rather than a count: §10.4's whole difficulty is
            # that nobody can verify a claim after the fact, so the offending
            # text has to survive to the draft row where a reviewer -- or a
            # redraft -- can see exactly what tripped the gate.
            json.dumps(list(gates.product_claims)) if gates.product_claims else None,
        ),
    )
    draft_id = cursor.lastrowid
    _persist_draft_keywords(conn, draft_id, keywords)
    return draft_id


def draft_for_broker(
    conn: sqlite3.Connection,
    broker_id: int,
    angle_client,
    draft_client,
    embedding_client,
) -> DraftResult:
    """Propose angles, write all three draft formats, and persist them.

    Loads the voice profile, proposes angles, picks the best one, writes the
    long-form (pillar) draft, then independently condenses it to medium-form
    and short-form, and persists one `angle` row plus one to three `draft`
    rows (`format='long'` always, `format='medium'` / `format='short'` each
    when its condensation succeeded).

    Nothing is written, and no client call is made, when: there is no voice
    profile row; the profile's judgement half never landed (classification
    failed, leaving `register`/`themes`/`audience_signal` NULL -- the same
    distinction `profile.ProfileResult.classified` makes, applied here so a
    broker with statistics-only "no profile" does not spend an angle call
    against nothing); angle proposal returns none; or the long draft comes
    back `None` (there is nothing to condense, so neither `write_medium` nor
    `write_short` is ever called -- spec §5: both condense from the long
    body, not the angle).

    Medium and short are independent condensation attempts once the long
    draft exists: both `write_medium` and `write_short` are always called,
    and either one returning `None` does not discard the good long draft or
    the other successful condensation -- `medium_written` / `short_written`
    report each failure separately.

    Every draft row carries `status='pending_review'`; nothing here ever
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

    # Spec §5b: keyword selection is per-format (the long/medium/short slots
    # differ), but always against this same angle+bank state, which is what
    # gives medium/short their subset-of-long guarantee -- see
    # `keywords.select_for_draft`'s docstring. Selection never blocks
    # drafting: an empty bank or nothing-qualifies returns
    # {"primary": None, "secondary": []}, and `DraftClient` degrades that to
    # "no keyword guidance in the prompt" (see `draft._keyword_guidance`).
    long_keywords = keyword_selection.select_for_draft(conn, "long", angle)
    long_body = draft_client.write_long(angle, profile, broker_name, keywords=long_keywords)
    if not long_body:
        return DraftResult(written=False)

    # Independent attempts: neither call short-circuits the other, and
    # either one failing must not stop the other from being written (spec
    # v0.6 §5's partial-failure semantics, extended from short-only to both).
    medium_keywords = keyword_selection.select_for_draft(conn, "medium", angle)
    medium_body = draft_client.write_medium(
        long_body, profile, broker_name, keywords=medium_keywords
    )
    short_keywords = keyword_selection.select_for_draft(conn, "short", angle)
    short_body = draft_client.write_short(long_body, profile, keywords=short_keywords)

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

    _insert_gated_draft(
        conn,
        angle_id=angle_id,
        broker_id=broker_id,
        body=long_body,
        fmt="long",
        profile=profile,
        embedding_client=embedding_client,
        keywords=long_keywords,
    )

    medium_written = False
    if medium_body:
        _insert_gated_draft(
            conn,
            angle_id=angle_id,
            broker_id=broker_id,
            body=medium_body,
            fmt="medium",
            profile=profile,
            embedding_client=embedding_client,
            keywords=medium_keywords,
        )
        medium_written = True

    short_written = False
    if short_body:
        _insert_gated_draft(
            conn,
            angle_id=angle_id,
            broker_id=broker_id,
            body=short_body,
            fmt="short",
            profile=profile,
            embedding_client=embedding_client,
            keywords=short_keywords,
        )
        short_written = True

    conn.commit()
    return DraftResult(written=True, medium_written=medium_written, short_written=short_written)
