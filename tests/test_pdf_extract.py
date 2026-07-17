import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdfplumber
import pytest

import pdf_fixtures
from core import pdf_extract
from core.pdf_extract import pdf_to_markdown


def _write(tmp_path, name, data: bytes):
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(data)
    return path


class TestFixtures:
    def test_gap_matches_the_measured_corpus(self, tmp_path):
        # The fixture must reproduce the real defect, or every test that asserts
        # the fix works would pass vacuously against a fixture with no bug in it.
        path = _write(tmp_path, "gapped", pdf_fixtures.gapped_words())
        with pdfplumber.open(path) as pdf:
            chars = pdf.pages[0].chars
        gaps = [round(b["x0"] - a["x1"], 2) for a, b in zip(chars, chars[1:])]
        assert max(gaps) == pytest.approx(2.89, abs=0.01)

    def test_bug_is_present_at_default_tolerance(self, tmp_path):
        path = _write(tmp_path, "gapped", pdf_fixtures.gapped_words())
        with pdfplumber.open(path) as pdf:
            assert pdf.pages[0].extract_text() == "differentstationary"


class TestText:
    def test_gapped_words_are_separated(self, tmp_path):
        path = _write(tmp_path, "gapped", pdf_fixtures.gapped_words())
        assert pdf_to_markdown(path) == "different stationary"

    def test_prose_only_pdf_has_no_table_markup(self, tmp_path):
        # markitdown emitted 104 fake "| --- |" rows for a page like this.
        path = _write(tmp_path, "prose", pdf_fixtures.prose_only())
        result = pdf_to_markdown(path)
        assert "Just a paragraph, no ruling lines anywhere." in result
        assert "| --- |" not in result


class TestTables:
    def test_ruled_grid_renders_as_a_markdown_table(self, tmp_path):
        path = _write(tmp_path, "ruled", pdf_fixtures.ruled_table())
        result = pdf_to_markdown(path)
        assert "| Header A | Header B |" in result
        assert "| --- | --- |" in result
        assert "| a1 | b1 |" in result
        assert "| a2 | b2 |" in result

    def test_prose_precedes_the_table_and_is_not_piped(self, tmp_path):
        path = _write(tmp_path, "ruled", pdf_fixtures.ruled_table())
        result = pdf_to_markdown(path)
        prose, table = "Intro prose above the table.", "| Header A | Header B |"
        assert result.index(prose) < result.index(table)
        assert prose in result.splitlines()  # its own line, no pipes wrapped round it

    def test_grid_is_blank_line_separated_from_prose(self, tmp_path):
        # Without a blank line before it, markdown will not parse the table.
        path = _write(tmp_path, "ruled", pdf_fixtures.ruled_table())
        result = pdf_to_markdown(path)
        assert "Intro prose above the table.\n\n| Header A | Header B |" in result

    def test_single_row_table_renders_as_a_plain_line(self, tmp_path):
        path = _write(tmp_path, "kv", pdf_fixtures.kv_table())
        result = pdf_to_markdown(path)
        assert result == "Frame type: Aluminium"
        assert "| --- |" not in result

    def test_pipe_in_a_cell_is_escaped(self, tmp_path):
        path = _write(tmp_path, "pipe", pdf_fixtures.pipe_cell())
        result = pdf_to_markdown(path)
        assert r"| a\|b | plain |" in result

    def test_blank_spacer_row_is_dropped(self, tmp_path):
        path = _write(tmp_path, "blank", pdf_fixtures.blank_row_table())
        result = pdf_to_markdown(path)
        assert result == "| Head | Other |\n| --- | --- |\n| a1 | b1 |"


class TestRatioThreshold:
    """Fix 1: X_TOLERANCE_RATIO replaces the absolute X_TOLERANCE. An absolute
    point value cannot port across font sizes -- see §13 of the design doc.
    """

    def test_small_font_gap_is_split_by_the_ratio(self, tmp_path):
        # Same TJ-gap construction as gapped_words(), but at a font size where
        # the resulting gap is 0.738pt in absolute terms -- the measured
        # Russian-patent case. ratio 0.12 * 6.0 = 0.72pt is small enough to
        # still treat this as a word break.
        path = _write(tmp_path, "gapped_small", pdf_fixtures.gapped_words_small_font())
        assert pdf_to_markdown(path) == "different stationary"

    def test_the_same_gap_would_stay_glued_at_the_old_absolute_tolerance(self, tmp_path):
        # Self-check mirroring TestFixtures above: proves this fixture actually
        # distinguishes a ratio from a fixed absolute number, rather than just
        # being a smaller copy of gapped_words(). The pre-revision design used
        # x_tolerance=2 (absolute); 0.738pt is under that, so it never split.
        path = _write(tmp_path, "gapped_small", pdf_fixtures.gapped_words_small_font())
        with pdfplumber.open(path) as pdf:
            assert pdf.pages[0].extract_text(x_tolerance=2) == "differentstationary"


class TestSingleColumnGrids:
    """Fix 2: a frame plus any intersecting rule makes a 1xN grid out of
    ordinary paragraphs. It must render as prose, exactly like the existing
    single-row case, not as a table.
    """

    def test_framed_prose_has_no_table_markup(self, tmp_path):
        path = _write(tmp_path, "framed", pdf_fixtures.framed_prose())
        result = pdf_to_markdown(path)
        assert "| --- |" not in result
        assert "First paragraph inside the frame." in result
        assert "Second paragraph inside the frame." in result


class TestCellBboxFiltering:
    """Fix 3: prose must be filtered against cell bboxes, not the table's hull
    bbox. Table.extract only ever reads inside cell bboxes, so any text
    sitting in a gap within the hull belongs to no cell and would otherwise
    vanish from the output entirely.
    """

    def test_text_in_a_table_hull_gap_is_not_swallowed(self, tmp_path, monkeypatch):
        # Fake a pathological table whose hull bbox spans the whole page but
        # whose only real cell is a tiny corner far from the prose. Hull-based
        # filtering (the old behaviour) would treat every character on the
        # page as "inside the table" and drop the prose; cell-based filtering
        # only excludes the tiny corner, so the prose survives.
        path = _write(tmp_path, "ruled", pdf_fixtures.ruled_table())
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]

            class FakeTable:
                bbox = (0, 0, 612, 792)

                @staticmethod
                def extract(**kwargs):
                    return [["x"]]

                rows = [SimpleNamespace(cells=[(0, 0, 10, 10)])]

            monkeypatch.setattr(page, "find_tables", lambda settings: [FakeTable()])
            result = pdf_extract._render_page(page)

        assert "Intro prose above the table." in result


class TestCellTextSettings:
    """Fix: `table.extract(**TEXT_SETTINGS)` in `_render_table` is the only
    thing standing between cell text and the 3pt default. `find_tables` does
    not propagate text settings to `Table.extract()`, so a call site that
    drops `**TEXT_SETTINGS` silently re-glues words inside cells even though
    every other test fixture uses ordinary space characters and would never
    notice. This must fail if `**TEXT_SETTINGS` is removed from that call.
    """

    def test_gapped_words_inside_a_ruled_cell_are_separated(self, tmp_path):
        path = _write(tmp_path, "gapped_cell", pdf_fixtures.gapped_words_in_cell())
        result = pdf_to_markdown(path)
        assert "different stationary" in result
        assert "differentstationary" not in result


class TestPipeEscaping:
    """Fix 4: pipe escaping happens at grid render, not in cell sanitisation.
    Single-row and single-column grids emit prose, where an escaped pipe would
    show a visible backslash that isn't in the source document.
    """

    def test_pipe_in_a_single_row_grid_is_not_escaped(self, tmp_path):
        path = _write(tmp_path, "pipe_row", pdf_fixtures.pipe_in_single_row())
        result = pdf_to_markdown(path)
        assert result == "a|b plain"
        assert "\\|" not in result
