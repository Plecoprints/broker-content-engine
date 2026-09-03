"""The `.gitignore` guarantees, asserted rather than assumed.

The remote is public, so "we'll remember not to commit that" is not a control.
These tests are cheap and they fail loudly the day someone widens a pattern
into `data/*.csv` and silently stops tracking the keyword banks, or narrows
one and lets the broker shortlist through.

`git check-ignore` is the authority here, not our own reading of the file --
gitignore precedence rules (later patterns, negations, directory-only
matching) are subtle enough that asking git directly is the only honest test.
"""
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git not available"
)


def _ignored(path: str) -> bool:
    """True if git would ignore `path`. `--no-index` so the answer is about
    the patterns, not about whether the file happens to be tracked already."""
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", "--", path],
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr.decode() or "git check-ignore failed")
    return result.returncode == 0


@pytest.mark.parametrize("path", [
    "brokers.csv",
    "data/brokers.csv",
    "data/brokers-pilot-2026-09.csv",
    ".env",
    ".env.local",
    "data/assets/hull-render.jpg",
    "data/private/rights-confirmation.pdf",
    "docs/private/legal-review.md",
    "docs/asset-rights-private.md",
])
def test_operator_inputs_are_ignored(path):
    """Each of these would matter on a public remote (spec §10.1, §10.7)."""
    assert _ignored(path), f"{path} is NOT ignored — it could be committed"


@pytest.mark.parametrize("path", [
    "data/keywords-approved.csv",
    "data/keywords-excluded.csv",
    "data/keyword_bank.sample.csv",
    "data/semrush-us-2026-09-01.csv",
    "src/bce/keywords.py",
    "STATUS.md",
])
def test_repository_content_is_not_ignored(path):
    """The other direction, and the one a careless broadening breaks: an
    over-wide rule like `data/*.csv` would stop tracking the keyword banks
    while looking like it had tightened security."""
    assert not _ignored(path), f"{path} IS ignored — it should be tracked"


# =============================================================================
# Semrush licence hygiene (legal review 2026-09-02)
# =============================================================================

import csv as _csv
import pathlib as _pathlib

_SEMRUSH_CSVS = [
    "data/semrush-us-2026-09-01.csv",
    "data/keywords-approved.csv",
    "data/keywords-excluded.csv",
    "data/keyword_bank.sample.csv",
]

#: Semrush's own commercial analysis, and the highest-sensitivity fields in any
#: export: CPC is monetary bid data and SERP Features is their SERP analysis,
#: which sits squarely inside ToS s6.1's "insights, analyses". Nothing in
#: `src/` reads either, so carrying them was pure exposure for zero utility.
_FORBIDDEN_COLUMNS = {"cpc (usd)", "cpc", "serp features", "serp_features"}


def _header(path: str) -> list[str]:
    text = _pathlib.Path(path).read_text(encoding="utf-8-sig")
    rows = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    return next(_csv.reader(rows), [])


@pytest.mark.parametrize("path", _SEMRUSH_CSVS)
def test_no_tracked_csv_carries_semrush_commercial_analysis(path):
    """Stripped 2026-09-02 and asserted here rather than remembered.

    `keywords.load_bank` silently drops unmapped columns, so re-adding these
    would break nothing and be noticed by nobody -- which is exactly the shape
    of a control that quietly stops holding. Same argument as the gitignore
    tests above: "we'll remember" is not a control.
    """
    present = {h.strip().lower() for h in _header(path)}
    assert not (present & _FORBIDDEN_COLUMNS), (
        f"{path} carries {sorted(present & _FORBIDDEN_COLUMNS)} — Semrush's own "
        "commercial analysis, which no code here reads"
    )


@pytest.mark.parametrize("path", _SEMRUSH_CSVS)
def test_every_semrush_file_states_its_provenance_and_licence_basis(path):
    """The artifact an auditor asks for first, and the one that answers the IT
    finding directly: where the data came from and under what permission."""
    head = _pathlib.Path(path).read_text(encoding="utf-8-sig")[:800].lower()
    assert "semrush" in head, f"{path}: no source stated"
    assert "not for redistribution" in head, f"{path}: no licence basis stated"


def test_semrush_metrics_never_reach_a_language_model():
    """Semrush ToS s3.3(r) forbids their outputs as LLM inputs. Keyword
    *phrases* are search strings people type into Google, not Semrush's
    creation; volume, difficulty and CPC are their estimates and analysis.

    The code is compliant today by design -- `draft._keyword_guidance`
    interpolates only `phrase` -- but `angles.AngleClient.keyword_source` is an
    unwired seam that would fold live Semrush results into a prompt. This test
    is what stops that landing with figures attached.
    """
    for module in ("draft", "llm", "angles", "profile"):
        source = _pathlib.Path(f"src/bce/{module}.py").read_text()
        for field in ("volume", "difficulty", "cpc"):
            offenders = [
                line.strip() for line in source.splitlines()
                if field in line.lower()
                and ("prompt" in line.lower() or "content" in line.lower()
                     or line.strip().startswith("f\"") or line.strip().startswith("f'"))
                and not line.strip().startswith("#")
            ]
            assert not offenders, f"{module}.py may put {field} in a prompt: {offenders}"
