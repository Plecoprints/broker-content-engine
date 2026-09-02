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
