"""Чистый слой конверсии: без FastAPI, без HTTP, без архива."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdf_fixtures
from trimitdown import convert as pure
from trimitdown.convert import (
    ConversionError,
    ConversionResult,
    convert_bytes,
    convert_path,
    count_tokens,
)


def test_convert_path_renders_a_ruled_table(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())

    result = convert_path(pdf)

    assert isinstance(result, ConversionResult)
    assert "|" in result.text            # настоящая таблица дошла как markdown-таблица
    assert result.unit == "page"
    assert result.units == 1
    assert result.tokens_after > 0


def test_convert_bytes_matches_convert_path(tmp_path):
    data = pdf_fixtures.prose_only()
    pdf = tmp_path / "prose.pdf"
    pdf.write_bytes(data)

    assert convert_bytes(data, ".pdf").text == convert_path(pdf).text


def test_unreadable_input_raises_conversion_error_not_http(tmp_path):
    # Чистый слой обязан бросать своё исключение: HTTPException здесь означал бы,
    # что FastAPI просочился обратно в ядро.
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not a pdf")

    with pytest.raises(ConversionError):
        convert_path(broken)


# tiktoken выводит имя файла кэша как sha1 от URL энкодинга. Значение
# детерминированное, поэтому его можно утверждать: если blob пропал из пакета, а
# каталог остался, tiktoken молча скачает его из сети.
CL100K_BLOB = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"


def test_count_tokens_uses_the_offline_cache():
    # Кэш едет в пакете как package data. Слабых проверок здесь две, и обе уже
    # были опробованы: count_tokens(...) > 0 проходит, когда путь не разрешился
    # вовсе (tiktoken качает BPE из сети, а сеть есть на всех раннерах CI), а
    # "каталог непуст" проходит, когда blob потерян при упаковке, но рядом лежит
    # README. Утверждать надо ровно тот файл, который нужен энкодингу.
    import os

    cache_dir = Path(os.environ["TIKTOKEN_CACHE_DIR"])
    assert cache_dir.is_dir(), f"кэш не разрешился: {cache_dir}"
    assert (cache_dir / CL100K_BLOB).is_file(), (
        f"blob cl100k_base отсутствует в {cache_dir}: счёт токенов уйдёт в сеть"
    )
    assert count_tokens("hello world") > 0


def test_pure_module_does_not_import_fastapi():
    # Инвариант границы слоёв. Ломается молча: FastAPI подтянется транзитивно и
    # CLI-пакет утяжелится на весь веб-стек, ничего при этом не сломав внешне.
    code = (
        "import sys, trimitdown.convert; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# Маршрутизация и оценка приехали сюда из tests/test_converter.py вместе с самой
# логикой: они проверяют ядро, а не HTTP. Держать их на веб-слое значило бы
# патчить имена на модуле, который этими объектами больше не владеет.
class TestPdfRouting:
    def test_pdf_routes_through_pdf_extract(self, monkeypatch):
        class Boom:
            def convert(self, path):
                raise AssertionError("markitdown must not see a .pdf")

        monkeypatch.setattr(pure, "md", Boom())
        monkeypatch.setattr(pure, "pdf_to_markdown", lambda path: "# From pdfplumber\n")
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 1)

        result = convert_bytes(b"%PDF-1.4 fake pdf bytes", ".pdf")

        assert result.text == "# From pdfplumber\n"

    def test_non_pdf_still_routes_through_markitdown(self, monkeypatch):
        class FakeResult:
            text_content = "# From markitdown\n"

        def boom(path):
            raise AssertionError("pdf_extract must not see a .docx")

        monkeypatch.setattr(pure.md, "convert", lambda path: FakeResult())
        monkeypatch.setattr(pure, "pdf_to_markdown", boom)

        result = convert_bytes(b"fake docx bytes", ".docx")

        assert result.text == "# From markitdown\n"

    def test_pdf_named_file_without_pdf_signature_routes_to_markitdown(self, monkeypatch):
        # markitdown dispatches by sniffing content, so an HTML/TXT file
        # misnamed ".pdf" used to convert fine through markitdown. Routing on
        # the suffix alone would silently 422 it instead; the %PDF magic-byte
        # check must fall through to markitdown for this case.
        class FakeResult:
            text_content = "# From markitdown\n"

        def boom(path):
            raise AssertionError("pdf_extract must not see non-PDF content")

        monkeypatch.setattr(pure.md, "convert", lambda path: FakeResult())
        monkeypatch.setattr(pure, "pdf_to_markdown", boom)

        result = convert_bytes(b"<html>not really a pdf</html>", ".pdf")

        assert result.text == "# From markitdown\n"

    def test_pdf_with_offset_marker_still_routes_to_pdf_extract(self, monkeypatch):
        # The %PDF marker is not guaranteed to sit at byte 0 -- real PDFs can
        # have a leading \r\n (or other junk) before the header, and
        # pdfplumber parses them fine. A byte-0-anchored check would send
        # these to markitdown, recreating the exact defects this extractor
        # exists to remove. The signature check must scan a window instead.
        class Boom:
            def convert(self, path):
                raise AssertionError("markitdown must not see a real PDF with an offset marker")

        monkeypatch.setattr(pure, "md", Boom())
        monkeypatch.setattr(pure, "pdf_to_markdown", lambda path: "# From pdfplumber\n")
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 1)

        result = convert_bytes(pdf_fixtures.offset_pdf_marker(), ".pdf")

        assert result.text == "# From pdfplumber\n"

    def test_pdf_gets_before_estimate(self, monkeypatch):
        monkeypatch.setattr(pure, "pdf_to_markdown", lambda path: "# Scanned doc\n")
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 4)

        result = convert_bytes(b"%PDF-1.4 fake pdf bytes", ".pdf")

        assert result.unit == "page"
        assert result.units == 4


class TestEstimateBeforeTokens:
    def test_pdf_uses_real_page_count(self, monkeypatch):
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 3)

        before, unit, units = pure._estimate_before_tokens(".pdf", "dummy.pdf")

        assert unit == "page"
        assert units == 3
        assert before == 3 * pure.TOKENS_PER_UNIT_ESTIMATE

    def test_pptx_uses_real_slide_count(self, monkeypatch):
        monkeypatch.setattr(pure, "_count_pptx_slides", lambda path: 5)

        before, unit, units = pure._estimate_before_tokens(".pptx", "dummy.pptx")

        assert unit == "slide"
        assert units == 5
        assert before == 5 * pure.TOKENS_PER_UNIT_ESTIMATE

    def test_other_formats_get_no_before_estimate(self):
        for suffix in [".docx", ".xlsx", ".xls", ".msg", ".txt"]:
            assert pure._estimate_before_tokens(suffix, "dummy") == (None, None, None)

    def test_page_count_failure_falls_back_to_none(self, monkeypatch):
        def boom(path):
            raise ValueError("corrupt pdf")

        monkeypatch.setattr(pure, "_count_pdf_pages", boom)

        assert pure._estimate_before_tokens(".pdf", "dummy.pdf") == (None, None, None)
