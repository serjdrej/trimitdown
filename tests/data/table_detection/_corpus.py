"""Corpus location for the one-off measurement scripts in this directory.

These scripts are not part of the test suite. They are kept so that every
threshold in the engine can be re-measured rather than taken on faith, and they
need the original corpus — third-party documents that are not in this
repository and never will be.

There is deliberately no default path: hardcoding one would ship somebody's
home directory to every reader of a public repository.

    set TRIMITDOWN_CORPUS=<directory holding the PDFs>
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
# Corpus-derived data lives outside the repo tree; see tests/conftest.py.
PRIVATE_DIR = Path(os.environ.get("TRIMITDOWN_PRIVATE") or REPO_ROOT.parent / "trimitdown-private")


def corpus_dir() -> Path:
    """The corpus directory, or exit with an explanation.

    `sys.exit` rather than `pytest.skip`: this runs at module level in plain
    scripts, where skip is not available and would raise.
    """
    raw = os.environ.get("TRIMITDOWN_CORPUS")
    if not raw:
        sys.exit("set TRIMITDOWN_CORPUS to the directory holding the PDF corpus")
    root = Path(raw)
    if not root.is_dir():
        sys.exit(f"TRIMITDOWN_CORPUS is not a directory: {root}")
    return root


def corpus_paths(file_ids) -> list[Path]:
    """Resolve opaque document ids to real paths under the corpus.

    labelset.jsonl names documents by id so the public repository carries no
    corpus filenames; `labelset-files.json` maps back and is gitignored.
    """
    mapping_file = PRIVATE_DIR / "labelset-files.json"
    if not mapping_file.exists():
        mapping_file = HERE / "labelset-files.json"  # old in-tree location
    if not mapping_file.exists():
        sys.exit(f"no local id -> filename mapping at {mapping_file}")
    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    root = corpus_dir()
    found = []
    for fid in file_ids:
        name = mapping.get(fid)
        if not name:
            sys.exit(f"no mapping entry for document id {fid}")
        hits = list(root.rglob(name))
        if not hits:
            sys.exit(f"document {fid} not found under TRIMITDOWN_CORPUS")
        found.append(hits[0])
    return found
