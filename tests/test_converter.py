import asyncio
import io
import sys
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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

        assert data == {"filename": "notes.md", "content": "# Hello\n"}
        assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Hello\n"

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
