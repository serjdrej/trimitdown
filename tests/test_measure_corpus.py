"""Tests for scripts/measure_corpus.py.

The script is the public reproduction path: it is what a reader runs to check
the engine's claims on documents nobody here has seen, and what they paste back
into an issue. Two properties matter and are asserted here -- that the metrics
count what they say they count, and that the pasteable summary carries no
filename from the reader's corpus.
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

import pdf_fixtures
from conftest import REPO_ROOT

# scripts/ is not a package, so the module is loaded by path rather than
# imported. Adding scripts/ to sys.path would put every one-off script in this
# repo on the import path for the whole test session.
SCRIPT = REPO_ROOT / "scripts" / "measure_corpus.py"
_spec = importlib.util.spec_from_file_location("measure_corpus", SCRIPT)
mc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mc)


class TestMetrics:
    def test_numbers_ignores_single_digits(self):
        # Single digits are too common in prose to carry signal about whether a
        # converter dropped or duplicated a document's data.
        assert mc.numbers_in("page 5 of 7") == {}

    def test_numbers_counts_multiplicity(self):
        # Multiplicity is the whole mechanism: a number emitted twice by a
        # converter that appears once in the page text is a duplicate, and
        # a Counter difference is what surfaces it.
        assert mc.numbers_in("12 and 12 and 34") == {"12": 2, "34": 1}

    def test_glued_run_counted(self):
        # 31 letters with no break -- two words fused, not a real word.
        text = "extraordinarilyuncharacteristic"
        assert mc.score(text, mc.numbers_in(""), has_grids=False)["glued"] == 1

    def test_ordinary_prose_is_not_glue(self):
        assert mc.score("perfectly ordinary prose", mc.numbers_in(""), False)["glued"] == 0

    def test_phantom_rows_only_on_gridless_documents(self):
        # Same output, two documents: rows on a page with no ruled grid are
        # invented; on a page that has one they may be correct, and this script
        # has no labels to tell which.
        table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        empty = mc.numbers_in("")
        assert mc.score(table, empty, has_grids=False)["phantom_rows"] == 3
        assert mc.score(table, empty, has_grids=True)["phantom_rows"] == 0

    def test_parity_measures_both_directions(self):
        baseline = mc.numbers_in("10 20 30")
        lost = mc.score("10 20", baseline, False)
        assert (lost["num_deficit"], lost["num_excess"]) == (1, 0)
        duplicated = mc.score("10 10 20 30", baseline, False)
        assert (duplicated["num_deficit"], duplicated["num_excess"]) == (0, 1)


@pytest.fixture
def corpus_of_two(tmp_path):
    """A two-document corpus whose filenames must never reach the summary."""
    root = tmp_path / "pdfs"
    root.mkdir()
    (root / "secret-patient-record.pdf").write_bytes(pdf_fixtures.ruled_table())
    (root / "another-private-name.pdf").write_bytes(pdf_fixtures.prose_only())
    return root


def test_summary_carries_no_filenames(tmp_path, corpus_of_two):
    details = tmp_path / "details.jsonl"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(corpus_of_two), "--details", str(details)],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    # The point of the split: stdout is what a reader pastes into an issue, so
    # it is counts only. The names live in the details file, which stays on
    # their machine. This repository's own history is why the two are separate.
    assert "secret-patient-record" not in result.stdout
    assert "another-private-name" not in result.stdout
    assert "| markitdown | TrimItDown |" in result.stdout

    rows = [json.loads(line) for line in details.read_text(encoding="utf-8").splitlines()]
    assert {row["file"] for row in rows} == {
        "secret-patient-record.pdf", "another-private-name.pdf",
    }


def test_limit_stops_early(tmp_path, corpus_of_two):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(corpus_of_two),
         "--details", str(tmp_path / "d.jsonl"), "--limit", "1"],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "documents: 1 " in result.stdout
