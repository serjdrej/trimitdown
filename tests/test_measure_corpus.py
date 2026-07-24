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


def test_same_document_in_two_collections_is_measured_once(tmp_path):
    # Two collections that share a document must be passed to ONE run. Measuring
    # them separately and adding the summaries counted the shared document twice
    # -- which is how a 891-document corpus was once published as 893, dragging
    # every total and both medians with it.
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        root.mkdir()
        root.joinpath("shared.pdf").write_bytes(pdf_fixtures.prose_only())
    b.joinpath("only-in-b.pdf").write_bytes(pdf_fixtures.ruled_table())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(a), str(b),
         "--details", str(tmp_path / "d.jsonl")],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "documents: 2 " in result.stdout


class TestBrokenSourceSplit:
    """The 885/6 population split, which used to live only in prose.

    A document that encodes almost no word spacing glues heavily in any
    converter. Folding a handful of them into the headline let six files carry
    1388 of markitdown's 1495 glued runs, and moved the published glue result
    from 2.0x to 3.2x in this engine's favour. The split has to be code.
    """

    @staticmethod
    def row(markitdown_glued, trimitdown_glued=0):
        return {
            "file": "x.pdf", "grids": 1, "bytes": 100, "notext": 0,
            "markitdown": {"glued": markitdown_glued, "tokens": 10, "s": 0.1},
            "trimitdown": {"glued": trimitdown_glued, "tokens": 9, "s": 0.1},
        }

    def test_broken_source_documents_leave_the_headline(self):
        rows = [self.row(0), self.row(3), self.row(508, 413)]
        well, broken = mc.split_by_source_quality(rows)
        assert [r["markitdown"]["glued"] for r in well] == [0, 3]
        assert [r["markitdown"]["glued"] for r in broken] == [508]

    def test_verdict_reads_the_stock_converter_never_our_own_output(self):
        # Otherwise the split could be tuned to drop whichever documents this
        # engine happens to lose on.
        rows = [self.row(0, 9999)]
        well, broken = mc.split_by_source_quality(rows)
        assert len(well) == 1 and not broken

    def test_threshold_is_inclusive_at_the_boundary(self):
        assert mc.BROKEN_SOURCE_GLUE == 50
        well, broken = mc.split_by_source_quality([self.row(50), self.row(51)])
        assert [r["markitdown"]["glued"] for r in well] == [50]
        assert [r["markitdown"]["glued"] for r in broken] == [51]


def test_aggregate_totals_one_subset_without_remeasuring():
    # Every headline figure must share one denominator. Accumulating while
    # measuring counted documents that parsed but failed to convert, so the
    # document count and the gridless count described different populations.
    # Deliberately asymmetric in the grid counts: with one gridless document out
    # of two, an inverted counter returns the same 1 and the assertion passes on
    # broken code.
    rows = [
        {"file": "a.pdf", "grids": 0, "bytes": 10, "notext": 2,
         "markitdown": {"glued": 1, "s": 0.5}, "trimitdown": {"glued": 0, "s": 0.25}},
        {"file": "b.pdf", "grids": 3, "bytes": 30, "notext": 0,
         "markitdown": {"glued": 4, "s": 1.5}, "trimitdown": {"glued": 2, "s": 0.75}},
        {"file": "c.pdf", "grids": 7, "bytes": 20, "notext": 0,
         "markitdown": {"glued": 0, "s": 0.0}, "trimitdown": {"glued": 0, "s": 0.0}},
    ]
    totals, elapsed, n_bytes, n_gridless, n_notext = mc.aggregate(rows)
    assert (n_bytes, n_gridless, n_notext) == (60, 1, 2)
    assert totals["markitdown"]["glued"] == 5
    assert totals["trimitdown"]["glued"] == 2
    # Timing is not a count and must stay out of the count columns.
    assert "s" not in totals["markitdown"]
    assert elapsed == {"markitdown": 2.0, "trimitdown": 1.0}


def test_broken_source_document_leaves_the_headline_in_a_real_run(tmp_path):
    """Pins the split at its point of use, which a unit test cannot do.

    split_by_source_quality is covered above in isolation, but nothing there
    sees whether main() still calls it. Replacing that one call with
    `well, broken = rows, []` leaves every other test in this file green while
    silently folding the broken-source documents back into the headline -- the
    exact incident the split exists to prevent, and the one that moved a
    published glue result from 2.0x to 3.2x.
    """
    root = tmp_path / "pdfs"
    root.mkdir()
    root.joinpath("clean.pdf").write_bytes(pdf_fixtures.prose_only())
    root.joinpath("no-spacing.pdf").write_bytes(pdf_fixtures.unspaced_lines())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--details", str(tmp_path / "d.jsonl")],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    # The headline counts the clean document alone...
    assert "documents: 1 " in result.stdout
    # ...and the other one is reported, not discarded.
    assert "Reported separately: 1 document" in result.stdout


def test_engine_markers_stay_out_of_the_parity_rows_in_a_real_run(tmp_path):
    """Pins without_engine_markers at its point of use.

    A page with no text layer renders as a marker naming the page number, and
    the baseline for that page is empty by definition -- so scored naively the
    page number reads as a digit the engine invented. That produced 837 phantom
    "duplicated digits" across the private corpora. Removing the exclusion from
    score() passes every unit test in this file, so the guarantee is asserted
    end to end instead.
    """
    root = tmp_path / "pdfs"
    root.mkdir()
    root.joinpath("scan.pdf").write_bytes(pdf_fixtures.image_only_page())
    details = tmp_path / "d.jsonl"

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "--details", str(details)],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr

    rows = [json.loads(line) for line in details.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    # Without the exclusion this is 1: the "1" of "on page 1".
    assert rows[0]["trimitdown"]["digit_excess"] == 0
    assert rows[0]["trimitdown"]["digit_deficit"] == 0


def test_documents_sharing_a_name_but_not_a_size_are_both_measured(tmp_path):
    """De-duplication must not cost a reader their own documents.

    The same document in two overlapping collections is one document. Two
    different documents that happen to share a basename are two -- a reader
    whose tree holds an invoice.pdf in every project folder must not silently
    measure one of them.
    """
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        root.mkdir()
    a.joinpath("doc.pdf").write_bytes(pdf_fixtures.prose_only())
    b.joinpath("doc.pdf").write_bytes(pdf_fixtures.ruled_table())

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(a), str(b),
         "--details", str(tmp_path / "d.jsonl")],
        capture_output=True, text=True, encoding="utf-8", cwd=REPO_ROOT,
    )
    assert result.returncode == 0, result.stderr
    assert "documents: 2 " in result.stdout
