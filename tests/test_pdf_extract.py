import pdfplumber
import pytest

import pdf_fixtures


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
