import asyncio
import io
import sys
import threading
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdf_fixtures
from core import converter
from core.converter import (
    convert_and_save,
    delete_file,
    list_archive,
    safe_path,
    safe_stem,
    save_unique,
)


def make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(content), filename=filename)


class TestSafeStem:
    def test_plain_name(self):
        assert safe_stem("report.pdf") == "report"

    def test_strips_special_characters(self):
        assert safe_stem('bad<>:"name.txt') == "bad____name"

    def test_path_separators_reduce_to_last_segment(self):
        # Path(...).stem runs before the regex, so embedded separators
        # are reduced to the final path segment first — a filename can't
        # smuggle a directory traversal through safe_stem() this way.
        assert safe_stem("a/b\\c?d*.txt") == "c_d_"

    def test_keeps_cyrillic(self):
        assert safe_stem("Отчёт.pdf") == "Отчёт"

    def test_empty_stem_falls_back_to_file(self):
        assert safe_stem("///.txt") == "file"


class TestSaveUnique:
    def test_first_save_uses_plain_name(self, tmp_path):
        name = save_unique(tmp_path, "report", "hello")
        assert name == "report.md"
        assert (tmp_path / "report.md").read_text(encoding="utf-8") == "hello"

    def test_collision_gets_numbered_suffix(self, tmp_path):
        first = save_unique(tmp_path, "report", "one")
        second = save_unique(tmp_path, "report", "two")
        assert first == "report.md"
        assert second == "report (2).md"
        assert (tmp_path / "report.md").read_text(encoding="utf-8") == "one"
        assert (tmp_path / "report (2).md").read_text(encoding="utf-8") == "two"

    def test_no_data_loss_under_concurrency(self, tmp_path):
        # Regression test for the TOCTOU race the code review found: the old
        # exists()-then-write() let two concurrent saves both pass the
        # exists() check for the same name, and the second write silently
        # clobbered the first instead of falling back to "(2)".
        results = []

        def worker(i):
            results.append(save_unique(tmp_path, "race", f"content-{i}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(set(results)) == 10
        saved = {p.name: p.read_text(encoding="utf-8") for p in tmp_path.glob("*.md")}
        assert len(saved) == 10


class TestSafePath:
    def test_existing_file(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        assert safe_path(tmp_path, "a.md") == (tmp_path / "a.md").resolve()

    def test_missing_file_raises_404(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            safe_path(tmp_path, "missing.md")
        assert exc.value.status_code == 404

    def test_path_traversal_raises_400(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            safe_path(tmp_path, "../outside.md")
        assert exc.value.status_code == 400


class TestListArchive:
    def test_empty_directory(self, tmp_path):
        assert list_archive(tmp_path) == []

    def test_lists_and_searches(self, tmp_path):
        (tmp_path / "alpha.md").write_text("a")
        (tmp_path / "beta.md").write_text("b")
        names = {item["filename"] for item in list_archive(tmp_path)}
        assert names == {"alpha.md", "beta.md"}
        filtered = list_archive(tmp_path, q="alp")
        assert [item["filename"] for item in filtered] == ["alpha.md"]


class TestDeleteFile:
    def test_deletes_existing_file(self, tmp_path):
        (tmp_path / "a.md").write_text("x")
        delete_file(tmp_path, "a.md")
        assert not (tmp_path / "a.md").exists()

    def test_missing_file_raises_404(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            delete_file(tmp_path, "missing.md")
        assert exc.value.status_code == 404


class TestConvertAndSave:
    def test_successful_conversion(self, tmp_path, monkeypatch):
        class FakeResult:
            text_content = "# Hello\n"

        monkeypatch.setattr(converter.md, "convert", lambda path: FakeResult())
        upload = make_upload("notes.docx", b"fake docx bytes")

        response = asyncio.run(convert_and_save(tmp_path, upload))

        assert response.status_code == 200
        assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Hello\n"

    def test_conversion_failure_raises_422(self, tmp_path, monkeypatch):
        def boom(path):
            raise ValueError("unsupported format")

        monkeypatch.setattr(converter.md, "convert", boom)
        upload = make_upload("broken.xyz", b"garbage")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(convert_and_save(tmp_path, upload))
        assert exc.value.status_code == 422
        assert not list(tmp_path.glob("*.md"))

    def test_oversized_upload_raises_413(self, tmp_path, monkeypatch):
        monkeypatch.setattr(converter, "MAX_UPLOAD_BYTES", 10)
        upload = make_upload("big.txt", b"this is way more than 10 bytes")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(convert_and_save(tmp_path, upload))
        assert exc.value.status_code == 413


class TestConvertOne:
    def test_returns_plain_dict(self, tmp_path, monkeypatch):
        class FakeResult:
            text_content = "# Hello\n"

        monkeypatch.setattr(converter.md, "convert", lambda path: FakeResult())
        upload = make_upload("notes.docx", b"fake docx bytes")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["filename"] == "notes.md"
        assert data["content"] == "# Hello\n"
        assert data["tokens"] == {
            "after": converter.count_tokens("# Hello\n"),
            "before": None,
            "unit": None,
            "units": None,
        }
        assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Hello\n"

    def test_pdf_gets_before_estimate(self, tmp_path, monkeypatch):
        monkeypatch.setattr(converter, "pdf_to_markdown", lambda path: "# Scanned doc\n")
        monkeypatch.setattr(converter, "_count_pdf_pages", lambda path: 4)
        upload = make_upload("scan.pdf", b"%PDF-1.4 fake pdf bytes")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["tokens"]["unit"] == "page"
        assert data["tokens"]["units"] == 4

    def test_oversized_upload_raises_413(self, tmp_path, monkeypatch):
        monkeypatch.setattr(converter, "MAX_UPLOAD_BYTES", 10)
        upload = make_upload("big.txt", b"this is way more than 10 bytes")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(converter._convert_one(tmp_path, upload))
        assert exc.value.status_code == 413

    def test_conversion_failure_raises_422(self, tmp_path, monkeypatch):
        def boom(path):
            raise ValueError("unsupported format")

        monkeypatch.setattr(converter.md, "convert", boom)
        upload = make_upload("broken.xyz", b"garbage")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(converter._convert_one(tmp_path, upload))
        assert exc.value.status_code == 422
        assert not list(tmp_path.glob("*.md"))

    def test_pdf_routes_through_pdf_extract(self, tmp_path, monkeypatch):
        class Boom:
            def convert(self, path):
                raise AssertionError("markitdown must not see a .pdf")

        monkeypatch.setattr(converter, "md", Boom())
        monkeypatch.setattr(converter, "pdf_to_markdown", lambda path: "# From pdfplumber\n")
        monkeypatch.setattr(converter, "_count_pdf_pages", lambda path: 1)
        upload = make_upload("doc.pdf", b"%PDF-1.4 fake pdf bytes")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["content"] == "# From pdfplumber\n"

    def test_non_pdf_still_routes_through_markitdown(self, tmp_path, monkeypatch):
        class FakeResult:
            text_content = "# From markitdown\n"

        def boom(path):
            raise AssertionError("pdf_extract must not see a .docx")

        monkeypatch.setattr(converter.md, "convert", lambda path: FakeResult())
        monkeypatch.setattr(converter, "pdf_to_markdown", boom)
        upload = make_upload("notes.docx", b"fake docx bytes")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["content"] == "# From markitdown\n"

    def test_pdf_named_file_without_pdf_signature_routes_to_markitdown(self, tmp_path, monkeypatch):
        # markitdown dispatches by sniffing content, so an HTML/TXT file
        # misnamed ".pdf" used to convert fine through markitdown. Routing on
        # the suffix alone would silently 422 it instead; the %PDF magic-byte
        # check must fall through to markitdown for this case.
        class FakeResult:
            text_content = "# From markitdown\n"

        def boom(path):
            raise AssertionError("pdf_extract must not see non-PDF content")

        monkeypatch.setattr(converter.md, "convert", lambda path: FakeResult())
        monkeypatch.setattr(converter, "pdf_to_markdown", boom)
        upload = make_upload("fake.pdf", b"<html>not really a pdf</html>")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["content"] == "# From markitdown\n"

    def test_pdf_with_offset_marker_still_routes_to_pdf_extract(self, tmp_path, monkeypatch):
        # The %PDF marker is not guaranteed to sit at byte 0 -- real PDFs can
        # have a leading \r\n (or other junk) before the header, and
        # pdfplumber parses them fine. A byte-0-anchored check would send
        # these to markitdown, recreating the exact defects this extractor
        # exists to remove. The signature check must scan a window instead.
        class Boom:
            def convert(self, path):
                raise AssertionError("markitdown must not see a real PDF with an offset marker")

        monkeypatch.setattr(converter, "md", Boom())
        monkeypatch.setattr(converter, "pdf_to_markdown", lambda path: "# From pdfplumber\n")
        monkeypatch.setattr(converter, "_count_pdf_pages", lambda path: 1)
        upload = make_upload("doc.pdf", pdf_fixtures.offset_pdf_marker())

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["content"] == "# From pdfplumber\n"


class TestCountTokens:
    def test_empty_string_is_zero_tokens(self):
        assert converter.count_tokens("") == 0

    def test_longer_text_has_more_tokens(self):
        short = converter.count_tokens("hello")
        longer = converter.count_tokens("hello world, this is a much longer piece of text")
        assert longer > short

    def test_deterministic(self):
        text = "The quick brown fox jumps over the lazy dog."
        assert converter.count_tokens(text) == converter.count_tokens(text)


class TestEstimateBeforeTokens:
    def test_pdf_uses_real_page_count(self, monkeypatch):
        monkeypatch.setattr(converter, "_count_pdf_pages", lambda path: 3)

        before, unit, units = converter._estimate_before_tokens(".pdf", "dummy.pdf")

        assert unit == "page"
        assert units == 3
        assert before == 3 * converter.TOKENS_PER_UNIT_ESTIMATE

    def test_pptx_uses_real_slide_count(self, monkeypatch):
        monkeypatch.setattr(converter, "_count_pptx_slides", lambda path: 5)

        before, unit, units = converter._estimate_before_tokens(".pptx", "dummy.pptx")

        assert unit == "slide"
        assert units == 5
        assert before == 5 * converter.TOKENS_PER_UNIT_ESTIMATE

    def test_other_formats_get_no_before_estimate(self):
        for suffix in [".docx", ".xlsx", ".xls", ".msg", ".txt"]:
            assert converter._estimate_before_tokens(suffix, "dummy") == (None, None, None)

    def test_page_count_failure_falls_back_to_none(self, monkeypatch):
        def boom(path):
            raise ValueError("corrupt pdf")

        monkeypatch.setattr(converter, "_count_pdf_pages", boom)

        assert converter._estimate_before_tokens(".pdf", "dummy.pdf") == (None, None, None)


class TestConvertBatch:
    def test_all_files_succeed(self, tmp_path, monkeypatch):
        class FakeResult:
            text_content = "converted"

        monkeypatch.setattr(converter.md, "convert", lambda path: FakeResult())
        files = [make_upload("a.txt", b"one"), make_upload("b.txt", b"two")]

        async def run():
            return [event async for event in converter.convert_batch(tmp_path, files)]

        events = asyncio.run(run())

        assert [e["status"] for e in events] == ["ok", "ok"]
        assert {e["filename"] for e in events} == {"a.txt", "b.txt"}
        assert (tmp_path / "a.md").read_text(encoding="utf-8") == "converted"
        assert (tmp_path / "b.md").read_text(encoding="utf-8") == "converted"

    def test_partial_failure_is_best_effort(self, tmp_path, monkeypatch):
        files = [make_upload("good.txt", b"ok"), make_upload("bad.txt", b"broken")]

        async def fake_convert_one(archive_dir, file):
            if file.filename == "bad.txt":
                raise HTTPException(status_code=422, detail="Не удалось сконвертировать файл: boom")
            return {"filename": "good.md", "content": "ok"}

        monkeypatch.setattr(converter, "_convert_one", fake_convert_one)

        async def run():
            return [event async for event in converter.convert_batch(tmp_path, files)]

        events = asyncio.run(run())

        by_name = {e["filename"]: e for e in events}
        assert by_name["good.txt"]["status"] == "ok"
        assert by_name["good.txt"]["saved_as"] == "good.md"
        assert by_name["bad.txt"]["status"] == "error"
        assert "boom" in by_name["bad.txt"]["detail"]

    def test_empty_batch_yields_nothing(self, tmp_path):
        async def run():
            return [event async for event in converter.convert_batch(tmp_path, [])]

        assert asyncio.run(run()) == []


class TestZipArchiveFiles:
    def test_zip_contains_requested_files(self, tmp_path):
        (tmp_path / "a.md").write_text("content A", encoding="utf-8")
        (tmp_path / "b.md").write_text("content B", encoding="utf-8")

        buffer = converter.zip_archive_files(tmp_path, ["a.md", "b.md"])

        with zipfile.ZipFile(buffer) as zf:
            assert set(zf.namelist()) == {"a.md", "b.md"}
            assert zf.read("a.md").decode("utf-8") == "content A"
            assert zf.read("b.md").decode("utf-8") == "content B"

    def test_path_traversal_name_raises_400(self, tmp_path):
        (tmp_path / "a.md").write_text("x", encoding="utf-8")

        with pytest.raises(HTTPException) as exc:
            converter.zip_archive_files(tmp_path, ["a.md", "../outside.md"])
        assert exc.value.status_code == 400

    def test_missing_name_raises_404(self, tmp_path):
        with pytest.raises(HTTPException) as exc:
            converter.zip_archive_files(tmp_path, ["missing.md"])
        assert exc.value.status_code == 404
