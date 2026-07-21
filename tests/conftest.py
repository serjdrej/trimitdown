"""Shared fixtures and the corpus gate.

Most of the suite runs on synthetic PDFs built by `pdf_fixtures.py` and needs
nothing external. A few tests measure the detection stage against real
documents. That corpus is third-party copyrighted material, it is not in this
repository and never will be, so those tests carry the `corpus` marker and skip
unless TRIMITDOWN_CORPUS points at a directory holding it.

There is deliberately no default path. A personal directory hardcoded here
would ship someone's home directory to every reader of a public repository.

    pytest -m "not corpus"   # what CI runs: no skips, no corpus needed
    pytest -m corpus         # the pre-release gate, on a machine with the corpus
"""

import json
import os
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TESTS_DIR.parent
LABEL_DIR = TESTS_DIR / "data" / "table_detection"
# Everything that carries a corpus filename lives OUTSIDE the repository tree,
# in a sibling directory, so it is impossible to commit -- no .gitignore rule to
# forget, no `git add -f` to slip past. Default: <repo>/../trimitdown-private,
# overridable with TRIMITDOWN_PRIVATE. This repo once published a corpus file
# listing; keeping that data out of the working tree entirely is the fix.
PRIVATE_DIR = Path(os.environ.get("TRIMITDOWN_PRIVATE") or REPO_ROOT.parent / "trimitdown-private")

# `labels.py` lives beside the labelset and is imported by name; the repo root
# carries `core`. Doing it here removes the hand-rolled sys.path lines that used
# to sit at the top of individual test modules.
for _path in (REPO_ROOT, LABEL_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "corpus: requires the real PDF corpus; set TRIMITDOWN_CORPUS to run",
    )


def corpus_root() -> Path | None:
    """The corpus directory, or None when it is not configured or not there."""
    raw = os.environ.get("TRIMITDOWN_CORPUS")
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


def corpus_file_names() -> dict[str, str]:
    """file_id -> original filename.

    labelset.jsonl identifies documents by opaque id so that the public repo
    carries no corpus filenames. The mapping back is local and gitignored; it
    only exists on a machine that owns the corpus.
    """
    mapping = PRIVATE_DIR / "labelset-files.json"
    if not mapping.exists():
        # Fallback to the old in-tree location for a machine not yet migrated.
        mapping = LABEL_DIR / "labelset-files.json"
    if not mapping.exists():
        return {}
    return json.loads(mapping.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def corpus() -> Path:
    root = corpus_root()
    if root is None:
        pytest.skip("set TRIMITDOWN_CORPUS to the directory holding the PDF corpus")
    return root
