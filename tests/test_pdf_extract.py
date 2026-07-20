import re
from types import SimpleNamespace

import pdfplumber
import pytest

import pdf_fixtures
import trimitdown_pdf as pdf_extract
from conftest import corpus_file_names
from trimitdown_pdf import TABLE_SETTINGS, pdf_to_markdown


def _write(tmp_path, name, data: bytes):
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(data)
    return path


def _n_tables(md: str) -> int:
    return sum(1 for line in md.splitlines() if re.fullmatch(r"\|(?:\s*---\s*\|)+", line.strip()))


class TestSourceTypes:
    """pdf_to_markdown takes a path or raw bytes; pipeline callers have bytes."""

    def test_bytes_and_path_agree(self, tmp_path):
        data = pdf_fixtures.ruled_table()
        from_path = pdf_to_markdown(_write(tmp_path, "ruled", data))
        from_bytes = pdf_to_markdown(data)
        assert from_bytes == from_path
        assert _n_tables(from_bytes) == 1

    def test_str_path_accepted(self, tmp_path):
        path = _write(tmp_path, "ruled", pdf_fixtures.ruled_table())
        assert pdf_to_markdown(str(path)) == pdf_to_markdown(path)


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
    """Fix: `table.extract(**TEXT_SETTINGS)` in the `_render_page` loop is the
    only thing standing between cell text and the 3pt default. `find_tables` does
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


class TestSelectionFirst:
    """Fix 5: classification happens before prose subtraction. A kept grid's
    cells are what gets excluded from prose -- a dropped grid (outer frame)
    contributes nothing, so its text flows back through extract_text_lines
    instead of vanishing or being rendered twice.
    """

    def test_fixture_has_two_grids(self, tmp_path):
        # Self-check mirroring TestFixtures above: proves the fixture actually
        # produces two separate ruled grids (outer frame + inner data table),
        # not one merged structure, before any test asserts on the fix.
        path = _write(tmp_path, "nested", pdf_fixtures.frame_with_nested_table())
        with pdfplumber.open(path) as pdf:
            assert len(pdf.pages[0].find_tables(TABLE_SETTINGS)) == 2

    def test_frame_around_a_table_is_not_itself_a_table(self, tmp_path):
        path = _write(tmp_path, "nested", pdf_fixtures.frame_with_nested_table())
        out = pdf_to_markdown(path)
        # exactly one markdown table (the inner one); the frame flows as prose
        assert _n_tables(out) == 1

    def test_nested_table_content_is_not_duplicated(self, tmp_path):
        path = _write(tmp_path, "nested", pdf_fixtures.frame_with_nested_table())
        out = pdf_to_markdown(path)
        assert out.count("innercellA1") == 1  # the marker text appears once, not twice

    def test_frame_paragraph_survives_as_prose(self, tmp_path):
        path = _write(tmp_path, "nested", pdf_fixtures.frame_with_nested_table())
        out = pdf_to_markdown(path)
        assert "paragraph in the frame" in out
        assert "| paragraph in the frame" not in out  # not wrapped in pipes

    # -- Containment backstop coverage --------------------------------------
    # The tests above never reach the containment backstop in _render_page
    # (~pdf_extract.py:111-119): frame_with_nested_table()'s outer frame is
    # single-column, so it fails is_real_table at classification and the
    # backstop never runs on it. real_table_with_nested_table() closes that
    # gap: its outer frame is itself a real 2-col table that passes
    # is_real_table on its own merits, so both grids reach the backstop and
    # only bbox containment (outer.bbox encloses inner.bbox) tells them apart.

    def test_fixture_has_two_real_table_grids(self, tmp_path):
        # Self-check mirroring TestFixtures/TestSelectionFirst above: proves
        # find_tables returns two separate grids and BOTH satisfy
        # is_real_table, or this fixture would prove nothing about the
        # backstop -- classification alone would already resolve it.
        path = _write(tmp_path, "real_nested", pdf_fixtures.real_table_with_nested_table())
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]
            tables = page.find_tables(TABLE_SETTINGS)
            assert len(tables) == 2
            for t in tables:
                rows = [[pdf_extract._cell_text(c) for c in row] for row in t.extract(**pdf_extract.TEXT_SETTINGS)]
                rows = [r for r in rows if any(r)]
                assert pdf_extract.is_real_table(rows)

    def test_only_the_inner_table_survives_as_markdown(self, tmp_path):
        path = _write(tmp_path, "real_nested", pdf_fixtures.real_table_with_nested_table())
        out = pdf_to_markdown(path)
        assert _n_tables(out) == 1

    def test_inner_table_content_is_not_duplicated(self, tmp_path):
        path = _write(tmp_path, "real_nested", pdf_fixtures.real_table_with_nested_table())
        out = pdf_to_markdown(path)
        assert out.count("nestedcell1") == 1

    def test_outer_frame_text_survives_as_prose(self, tmp_path):
        path = _write(tmp_path, "real_nested", pdf_fixtures.real_table_with_nested_table())
        out = pdf_to_markdown(path)
        assert "framerowA" in out
        assert "| framerowA" not in out  # not wrapped in pipes -- it's prose, not the table


@pytest.mark.corpus
class TestRealDocumentAcceptance:
    """Real-file acceptance anchor. Binds one of the four documents from the
    corpus (see rfsweep.py for the full 695-file parity sweep) so a future
    change can't silently regress content fidelity on it.

    The document is a third-party datasheet and is not in this repository. It
    is identified by opaque id and resolved through the local, gitignored
    mapping, so a checkout without the corpus resolves nothing and skips.
    """

    FILE_ID = "b5beaa148386"

    def test_frame_dropped_real_table_kept(self, corpus):
        name = corpus_file_names().get(self.FILE_ID)
        if not name:
            pytest.skip("no local id -> filename mapping for the acceptance document")
        hits = list(corpus.rglob(name))
        if not hits:
            pytest.skip("acceptance document not found under TRIMITDOWN_CORPUS")
        out = pdf_to_markdown(hits[0])
        assert _n_tables(out) == 1                        # only the real grid; the frame flows as prose
        # The ruled grid captured only 3 of the datasheet's 4 data columns (15/22/32),
        # NOT 46 -- find_tables missed the 46 column's ruling. This is the partial-grid
        # defect (see "Product decision required" in the Task 3 brief); the test
        # documents it, it does not bless it. What matters for content fidelity: the 46
        # column's values must not vanish -- when the frame is dropped its text flows
        # back as prose.
        assert "| ГОСТ 33 | 15,6 | 22,5 | 32,6 |" in out  # the captured 3-column grid
        assert "46,1" in out                              # the dropped 46 column survives as prose
        # the frame's paragraph flows as prose, not a pipe row
        assert "| Масло гидравлическое" not in out
