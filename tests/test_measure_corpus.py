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
    def test_digits_counts_multiplicity(self):
        # Multiplicity is the whole mechanism: a digit emitted twice by a
        # converter that appears once in the page text is a duplicate, and
        # a Counter difference is what surfaces it.
        assert mc.digits_in("12 and 12 and 34") == {"1": 2, "2": 2, "3": 1, "4": 1}

    def test_glued_run_counted(self):
        # 31 letters with no break -- two words fused, not a real word.
        text = "extraordinarilyuncharacteristic"
        assert mc.score(text, mc.digits_in(""), has_grids=False)["glued"] == 1

    def test_ordinary_prose_is_not_glue(self):
        assert mc.score("perfectly ordinary prose", mc.digits_in(""), False)["glued"] == 0

    def test_phantom_rows_only_on_gridless_documents(self):
        # Same output, two documents: rows on a page with no ruled grid are
        # invented; on a page that has one they may be correct, and this script
        # has no labels to tell which.
        table = "| a | b |\n| --- | --- |\n| 1 | 2 |"
        empty = mc.digits_in("")
        assert mc.score(table, empty, has_grids=False)["phantom_rows"] == 3
        assert mc.score(table, empty, has_grids=True)["phantom_rows"] == 0

    def test_mojibake_counts_the_latin1_decoded_cyrillic_range(self):
        # "Привет" as cp1251 bytes read back as latin-1 -- the exact shape the
        # row exists to spot. Every character lands in U+00C0-U+00FF.
        text = "Привет".encode("cp1251").decode("latin-1")
        assert mc.score(text, mc.digits_in(""), False)["mojibake"] == len(text)

    def test_clean_text_scores_no_mojibake(self):
        assert mc.score("ordinary prose", mc.digits_in(""), False)["mojibake"] == 0
        assert mc.score("Привет, мир", mc.digits_in(""), False)["mojibake"] == 0

    def test_document_flag_separates_mis_decoding_from_accented_prose(self):
        # The character count alone cannot tell a mis-decoded document from a
        # French one; the per-document share is what does. A sentence with a
        # few accents must not trip the flag, a wholly mis-decoded one must.
        accented = mc.score("a very ordinary French sentence with é and à in it",
                            mc.digits_in(""), False)
        assert accented["mojibake"] == 2
        assert accented["mojibake_doc"] == 0

        garbled = "Привет мир".encode("cp1251").decode("latin-1")
        assert mc.score(garbled, mc.digits_in(""), False)["mojibake_doc"] == 1

    def test_empty_output_does_not_divide_by_zero(self):
        assert mc.score("", mc.digits_in(""), False)["mojibake_doc"] == 0

    def test_parity_measures_both_directions(self):
        baseline = mc.digits_in("10 20 30")
        lost = mc.score("10 20", baseline, False)
        assert (lost["digit_deficit"], lost["digit_excess"]) == (2, 0)
        duplicated = mc.score("10 10 20 30", baseline, False)
        assert (duplicated["digit_deficit"], duplicated["digit_excess"]) == (0, 2)

    def test_parity_ignores_where_a_cell_boundary_falls(self):
        # The reason this row counts digits and not number tokens. Splitting
        # "10" across two cells emits the same digits in the same quantity, so
        # parity stays clean; the token metric it replaced scored this as a
        # number lost, and on the private corpora that one effect accounted for
        # every "number lost" it ever reported.
        baseline = mc.digits_in("10 20 30")
        split = mc.score("| 1 | 0 | 20 | 30 |", baseline, False)
        assert (split["digit_deficit"], split["digit_excess"]) == (0, 0)


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


def test_limit_sample_is_seeded(tmp_path):
    # A --limit run must be reproducible: the same seed picks the same
    # documents, so a summary someone reports can be regenerated.
    root = tmp_path / "pdfs"
    root.mkdir()
    for i in range(6):
        root.joinpath(f"doc{i}.pdf").write_bytes(pdf_fixtures.prose_only())

    def sampled(seed):
        details = tmp_path / f"d{seed}.jsonl"
        subprocess.run(
            [sys.executable, str(SCRIPT), str(root), "--details", str(details),
             "--limit", "3", "--seed", str(seed)],
            capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT, check=True,
        )
        rows = [json.loads(l) for l in details.read_text(encoding="utf-8").splitlines()]
        return {row["file"] for row in rows}

    assert sampled(0) == sampled(0)          # reproducible
    assert len(sampled(0)) == 3              # honours the limit
    # The seed actually varies the draw. Two specific seeds could coincide
    # (20 possible 3-of-6 samples), so assert across several that the sample
    # is not constant -- that would mean the seed is ignored.
    assert len({frozenset(sampled(s)) for s in range(6)}) > 1
