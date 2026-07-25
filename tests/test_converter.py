import asyncio
import io
import sys
import threading
import zipfile
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
    save_unique,
)
from trimitdown.convert import ConversionError, ConversionResult, safe_stem


def make_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(io.BytesIO(content), filename=filename)


def stub_conversion(monkeypatch, text: str, **fields):
    """Подменить ядро на границе, которой владеет веб-слой.

    Веб-слой знает про convert_bytes и больше ни про что: маршрутизация по типу
    файла, счёт страниц и токенов проверяются в tests/test_convert_pure.py -- на
    том модуле, который этими объектами владеет.
    """
    result = ConversionResult(
        text=text,
        tokens_after=fields.get("tokens_after"),
        tokens_before=fields.get("tokens_before"),
        unit=fields.get("unit"),
        units=fields.get("units"),
    )
    monkeypatch.setattr(converter, "convert_bytes", lambda data, suffix: result)
    return result


def stub_conversion_failure(monkeypatch, message: str = "unsupported format"):
    def fail(data, suffix):
        raise ConversionError(message)

    monkeypatch.setattr(converter, "convert_bytes", fail)


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
        stub_conversion(monkeypatch, "# Hello\n")
        upload = make_upload("notes.docx", b"fake docx bytes")

        response = asyncio.run(convert_and_save(tmp_path, upload))

        assert response.status_code == 200
        assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# Hello\n"

    def test_conversion_failure_raises_422(self, tmp_path, monkeypatch):
        stub_conversion_failure(monkeypatch)
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
        # Счёт токенов делает ядро; веб-слой обязан лишь донести его до JSON
        # неизменным. converter.count_tokens здесь -- тот самый реэкспорт.
        stub_conversion(
            monkeypatch, "# Hello\n", tokens_after=converter.count_tokens("# Hello\n")
        )
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

    def test_token_stats_reach_the_response_unchanged(self, tmp_path, monkeypatch):
        # Оценка before/unit/units считается в ядре, но наружу её отдаёт этот
        # слой. Тест держит именно перекладку полей: раньше она была расчётом
        # здесь же, теперь -- копированием из ConversionResult.
        stub_conversion(
            monkeypatch, "# Scanned doc\n", tokens_after=7, tokens_before=9000,
            unit="page", units=4,
        )
        upload = make_upload("scan.pdf", b"%PDF-1.4 fake pdf bytes")

        data = asyncio.run(converter._convert_one(tmp_path, upload))

        assert data["tokens"] == {
            "after": 7,
            "before": 9000,
            "unit": "page",
            "units": 4,
        }

    def test_oversized_upload_raises_413(self, tmp_path, monkeypatch):
        monkeypatch.setattr(converter, "MAX_UPLOAD_BYTES", 10)
        upload = make_upload("big.txt", b"this is way more than 10 bytes")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(converter._convert_one(tmp_path, upload))
        assert exc.value.status_code == 413

    def test_conversion_failure_raises_422(self, tmp_path, monkeypatch):
        stub_conversion_failure(monkeypatch)
        upload = make_upload("broken.xyz", b"garbage")

        with pytest.raises(HTTPException) as exc:
            asyncio.run(converter._convert_one(tmp_path, upload))
        assert exc.value.status_code == 422
        assert not list(tmp_path.glob("*.md"))

    def test_suffix_reaches_the_core_for_routing(self, tmp_path, monkeypatch):
        # Ядро маршрутизирует по суффиксу, а взять его можно только из имени
        # UploadFile -- это знание веб-слоя. Сама маршрутизация проверяется в
        # tests/test_convert_pure.py::TestPdfRouting.
        seen = {}

        def spy(data, suffix):
            seen["suffix"] = suffix
            seen["data"] = data
            return ConversionResult(
                text="ok", tokens_after=1, tokens_before=None, unit=None, units=None
            )

        monkeypatch.setattr(converter, "convert_bytes", spy)
        upload = make_upload("Отчёт.PDF", b"%PDF-1.4 fake pdf bytes")

        asyncio.run(converter._convert_one(tmp_path, upload))

        assert seen["suffix"] == ".PDF"
        assert seen["data"] == b"%PDF-1.4 fake pdf bytes"


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


class TestPublicSurface:
    def test_core_converter_still_exports_the_names_the_apps_import(self):
        # Эти девять имён -- объявленная публичная поверхность core.converter,
        # и она держится намеренно, но по разным причинам. convert_and_save,
        # convert_batch, list_archive, delete_file, safe_path и
        # zip_archive_files не менялись при расщеплении: server_app.py и
        # docker-server/app.py берут их из core.converter, поэтому удаление
        # сломает импорт в обоих приложениях. count_tokens и safe_stem
        # (реэкспорт из ядра) и save_unique (определён здесь) в продакшене
        # никто извне не зовёт -- их единственный вызывающий это тест-сьют,
        # который упражняет их через core.converter. Без этого теста
        # «неиспользуемый импорт» однажды вычистят -- и в первом случае оба
        # приложения упадут на импорте, а во втором тест-сьют молча потеряет
        # покрытие.
        for name in (
            "convert_and_save",
            "convert_batch",
            "list_archive",
            "delete_file",
            "safe_path",
            "save_unique",
            "zip_archive_files",
            "safe_stem",
            "count_tokens",
        ):
            assert hasattr(converter, name), f"core.converter потерял {name}"

    def test_web_layer_no_longer_owns_conversion_internals(self):
        # Обратная сторона того же шва: имена конверсии обязаны исчезнуть с
        # веб-слоя, иначе тест снова начнёт патчить модуль, который объектом не
        # владеет, и позеленеет над мёртвым кодом.
        for name in ("md", "pdf_to_markdown", "_estimate_before_tokens",
                     "_count_pdf_pages", "_count_pptx_slides", "TOKENS_PER_UNIT_ESTIMATE",
                     "tiktoken", "_get_encoding", "_encoding"):
            assert not hasattr(converter, name), (
                f"core.converter всё ещё держит {name} -- вторая копия логики конверсии"
            )


class TestConvertBatch:
    def test_all_files_succeed(self, tmp_path, monkeypatch):
        stub_conversion(monkeypatch, "converted")
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


def test_web_layer_delegates_to_the_pure_core(tmp_path, monkeypatch):
    # Веб-слой обязан звать ядро, а не держать вторую копию логики конверсии.
    # Без этого теста расщепление можно откатить обратным копипастом, и ни один
    # другой тест этого не заметит.
    from trimitdown import convert as pure

    called = {}

    def fake_convert_bytes(data, suffix):
        called["suffix"] = suffix
        return pure.ConversionResult(
            text="stub", tokens_after=1, tokens_before=None, unit=None, units=None
        )

    monkeypatch.setattr(converter, "convert_bytes", fake_convert_bytes)

    response = asyncio.run(
        convert_and_save(tmp_path, make_upload("x.pdf", b"%PDF-1.4"))
    )

    assert called["suffix"] == ".pdf"
    assert b"stub" in response.body


def test_conversion_failure_becomes_422_not_a_crash(tmp_path, monkeypatch):
    from trimitdown.convert import ConversionError

    def fail(data, suffix):
        raise ConversionError("boom")

    monkeypatch.setattr(converter, "convert_bytes", fail)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(convert_and_save(tmp_path, make_upload("x.pdf", b"%PDF-1.4")))
    assert exc.value.status_code == 422


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
