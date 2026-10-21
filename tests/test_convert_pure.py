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


def test_convert_bytes_cleans_up_its_temp_file(monkeypatch):
    # convert_bytes writes the caller's bytes into a NamedTemporaryFile(delete=False)
    # because both anydoc and our own PDF engine read from a path, not bytes.
    # Nothing else ever references that path once convert_path returns, so if the
    # cleanup is ever dropped, every conversion silently leaves a copy of the
    # uploaded document behind in the system temp directory -- a privacy leak that
    # does not change the returned text at all. Capture the exact path tempfile
    # hands back and assert it is gone once convert_bytes returns.
    created_paths = []
    real_named_temp_file = pure.tempfile.NamedTemporaryFile

    def spying_named_temp_file(*args, **kwargs):
        tmp = real_named_temp_file(*args, **kwargs)
        created_paths.append(tmp.name)
        return tmp

    monkeypatch.setattr(pure.tempfile, "NamedTemporaryFile", spying_named_temp_file)

    convert_bytes(pdf_fixtures.prose_only(), ".pdf")

    assert created_paths, "convert_bytes never created a temp file -- fixture is not exercising cleanup"
    assert not Path(created_paths[0]).exists(), (
        f"convert_bytes left its temp file behind: {created_paths[0]}"
    )


def test_unreadable_input_raises_conversion_error_not_http(tmp_path):
    # Чистый слой обязан бросать своё исключение: HTTPException здесь означал бы,
    # что FastAPI просочился обратно в ядро.
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not a pdf")

    with pytest.raises(ConversionError):
        convert_path(broken)


def test_unopenable_file_raises_conversion_error_not_the_raw_os_error(tmp_path):
    # convert_path's header read used to happen before the try block, so a file
    # that exists but cannot be opened (permission denied, locked, device error)
    # raised the raw OSError straight through -- a traceback in the CLI and a 500
    # where a 422 belonged in the web layer. A directory is the simplest portable
    # way to trigger that: it passes as a path, but open(dir, "rb") raises
    # PermissionError/IsADirectoryError on both Windows and POSIX. Verified on
    # this machine (Windows): open() on a directory raises PermissionError.
    directory = tmp_path / "not_a_file.pdf"
    directory.mkdir()

    with pytest.raises(ConversionError):
        convert_path(directory)


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


def test_convert_path_does_not_import_fastapi():
    # Merely importing the module (the check above) never exercises a lazy
    # `import fastapi` hidden inside a function body -- that only lands in
    # sys.modules once the function actually runs. The plain pip/uvx package
    # has no FastAPI installed at all, so a lazy import here would not just
    # bloat the CLI, it would crash it outright the first time convert_path
    # is called. Actually calling convert_path is the only way to catch that.
    code = (
        "import sys, tempfile, os; "
        "from trimitdown.convert import convert_path; "
        "fd, path = tempfile.mkstemp(suffix='.txt'); "
        "os.close(fd); "
        "open(path, 'w', encoding='utf-8').write('hello world'); "
        "convert_path(path); "
        "os.unlink(path); "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


# Маршрутизация и оценка приехали сюда из tests/test_converter.py вместе с самой
# логикой: они проверяют ядро, а не HTTP. Держать их на веб-слое значило бы
# патчить имена на модуле, который этими объектами больше не владеет.
#
# Since 0.2 the PDF side is trimitdown.pdf_route. These tests replace route_pdf
# on the convert module with a one-page accept route, so they still say only
# which way a file goes; how pages are routed is test_pdf_route.py's business.
def _fake_route(text):
    from trimitdown.pdf_route import PageRoute

    return lambda path: [PageRoute(page=1, path="accept", reasons=(), text=text)]


class TestPdfRouting:
    def test_pdf_routes_through_pdf_extract(self, monkeypatch):
        def boom(path, suffix, head):
            raise AssertionError("the office/text path must not see a .pdf")

        monkeypatch.setattr(pure, "_convert_other", boom)
        monkeypatch.setattr(pure, "route_pdf", _fake_route("# From the PDF route\n"))
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 1)

        result = convert_bytes(b"%PDF-1.4 fake pdf bytes", ".pdf")

        assert result.text == "# From the PDF route\n"

    def test_uppercase_suffix_still_routes_through_pdf_extract(self, monkeypatch):
        # Суффикс приходит с диска/имени файла как есть -- нормализация регистра
        # это забота ядра (convert_path лоуэркейсит его перед сравнением).
        # Каждый другой тест в этом классе передаёт литерал ".pdf" уже в нижнем
        # регистре, так что удаление этой нормализации в convert_path останется
        # незамеченным без этого теста: файл "отчёт.PDF" молча уйдёт в
        # office-пути вместо нашего экстрактора.
        def boom(path, suffix, head):
            raise AssertionError("the office/text path must not see a .PDF")

        monkeypatch.setattr(pure, "_convert_other", boom)
        monkeypatch.setattr(pure, "route_pdf", _fake_route("# From the PDF route\n"))
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 1)

        result = convert_bytes(b"%PDF-1.4 fake pdf bytes", ".PDF")

        assert result.text == "# From the PDF route\n"

    def test_non_pdf_still_routes_through_anydoc(self, monkeypatch):
        def boom(path):
            raise AssertionError("the PDF route must not see a .docx")

        monkeypatch.setattr(pure, "_anydoc_to_markdown", lambda path: "# From anydoc\n")
        monkeypatch.setattr(pure, "route_pdf", boom)

        result = convert_bytes(b"fake docx bytes", ".docx")

        assert result.text == "# From anydoc\n"

    def test_pdf_named_file_without_pdf_signature_leaves_the_pdf_route(self, monkeypatch):
        # A page saved with the wrong extension used to convert fine. Routing on
        # the suffix alone would refuse it instead; the %PDF magic-byte check
        # must hand it to the non-PDF path, which here sniffs it as HTML. The
        # real HTML converter runs (no stub), so a route that sent it anywhere
        # else would not produce the heading.
        def boom(path):
            raise AssertionError("the PDF route must not see non-PDF content")

        monkeypatch.setattr(pure, "route_pdf", boom)

        result = convert_bytes(b"<html><body><h1>Not a PDF</h1></body></html>", ".pdf")

        assert result.text == "# Not a PDF"

    def test_pdf_with_offset_marker_still_routes_to_pdf_extract(self, monkeypatch):
        # The %PDF marker is not guaranteed to sit at byte 0 -- real PDFs can
        # have a leading \r\n (or other junk) before the header, and
        # pdfplumber parses them fine. A byte-0-anchored check would send
        # these to the office path, recreating the exact defects this extractor
        # exists to remove. The signature check must scan a window instead.
        def boom(path, suffix, head):
            raise AssertionError("the office/text path must not see a real PDF with an offset marker")

        monkeypatch.setattr(pure, "_convert_other", boom)
        monkeypatch.setattr(pure, "route_pdf", _fake_route("# From the PDF route\n"))
        monkeypatch.setattr(pure, "_count_pdf_pages", lambda path: 1)

        result = convert_bytes(pdf_fixtures.offset_pdf_marker(), ".pdf")

        assert result.text == "# From the PDF route\n"

    def test_pdf_gets_before_estimate(self, monkeypatch):
        monkeypatch.setattr(pure, "route_pdf", _fake_route("# Scanned doc\n"))
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


def test_converting_a_pdf_imports_neither_anydoc_nor_markdownify(tmp_path):
    """A PDF must not wake the office converters.

    anydoc and markdownify (with BeautifulSoup) are the `office` extra; the base
    install does not have them, so an import at module level would not slow the
    PDF path down, it would break it. The ML-model argument of the markitdown
    era (magika, onnxruntime, a coloured stderr warning) is gone with markitdown,
    but the contract is the same: the PDF route imports none of it. Moving
    either import to the top of convert.py must fail this test (verified).
    Run in a fresh interpreter: another test may already have imported them.
    """
    import subprocess
    import sys

    import pdf_fixtures

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())
    probe = (
        "import sys\n"
        "from trimitdown.convert import convert_path\n"
        f"convert_path({str(pdf)!r})\n"
        "print(sorted(m for m in ('anydoc', 'markdownify', 'bs4', 'markitdown', 'magika', 'onnxruntime')"
        " if m in sys.modules))\n"
    )
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=300)

    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "[]"


def test_an_office_format_without_the_extra_says_what_to_install(tmp_path, monkeypatch):
    """Without anydoc the error names the extra, not an import failure.

    The converters are the `office` extra; a bare ImportError would leave an
    agent guessing. Removing the ImportError handling around `import anydoc`
    must fail this test (verified).
    """
    import pytest

    monkeypatch.setitem(sys.modules, "anydoc", None)
    doc = tmp_path / "report.docx"
    doc.write_bytes(b"PK\x03\x04 not read, the import fails first")

    with pytest.raises(pure.ConversionError, match=r"trimitdown\[office\]"):
        pure.convert_path(doc)


def test_html_without_the_extra_says_what_to_install(tmp_path, monkeypatch):
    """The HTML path has its own lazy import and needs the same message.

    Removing the ImportError handling around `import markdownify` must fail
    this test (verified).
    """
    import pytest

    monkeypatch.setitem(sys.modules, "markdownify", None)
    page = tmp_path / "page.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")

    with pytest.raises(pure.ConversionError, match=r"trimitdown\[office\]"):
        pure.convert_path(page)
