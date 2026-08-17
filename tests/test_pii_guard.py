"""Regression coverage for the staged-content PII guard."""

import os
import shutil
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / ".githooks" / "pre-commit"


def _run_guard(tmp_path: Path, content: str) -> subprocess.CompletedProcess[str]:
    """Stage one file in a disposable repo and run the hook through POSIX sh."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    hook_dir = repo / ".githooks"
    hook_dir.mkdir()
    shutil.copyfile(HOOK, hook_dir / "pre-commit")
    (repo / "probe.txt").write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "probe.txt"], check=True)

    env = os.environ.copy()
    env["TRIMITDOWN_PRIVATE"] = str(tmp_path / "no-private-patterns")
    return subprocess.run(
        ["sh", ".githooks/pre-commit"],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _email() -> str:
    # Keep the generic fixture shape out of this test's own staged source: the
    # hook deliberately scans tests too, and a literal here would block a real
    # commit before this isolated-repository test could run.
    return "someone" + "@" + "example" + ".com"


def test_pii_guard_blocks_email_after_two_leading_pluses(tmp_path: Path):
    """A content ++ must not be mistaken for git's +++ file header.

    This would pass on the broken hook if it only checked that the hook ran;
    asserting rejection makes the pre-fix bypass a failing regression test.
    """
    result = _run_guard(tmp_path, "++" + _email() + "\n")

    assert result.returncode == 1, result.stderr


def test_pii_guard_blocks_email_after_one_leading_plus(tmp_path: Path):
    """Removing exactly one indicator must preserve a real leading plus."""
    result = _run_guard(tmp_path, "+" + _email() + "\n")

    assert result.returncode == 1, result.stderr


def test_pii_guard_allows_a_route_decorator(tmp_path: Path):
    """The diff indicator must not turn required decorator syntax into an email."""
    result = _run_guard(tmp_path, '@app.get("/api/thing")\n')

    assert result.returncode == 0, result.stderr
