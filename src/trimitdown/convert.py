"""Чистая конверсия документа в markdown.

Ни FastAPI, ни HTTP, ни архива: на вход путь или байты, на выходе текст и
счётчики. Веб-обёртки живут в core/converter.py и зовут этот модуль. Граница
закрыта тестом (tests/test_convert_pure.py::test_pure_module_does_not_import_fastapi):
импорт fastapi отсюда утяжелил бы CLI-пакет на весь веб-стек, ничего при этом не
сломав внешне -- то есть незаметно.
"""
import os
import re
import tempfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import tiktoken

from markitdown import MarkItDown

from pdfminer.pdfpage import PDFPage
from pptx import Presentation

from trimitdown_pdf import pdf_to_markdown

md = MarkItDown()

# Кэш едет внутри пакета как package data. Path(__file__) сработал бы для обычной
# установки, но не переживает упаковку; resources.files находит его и там, и в
# рабочем дереве. Без этого tiktoken при первом счёте полезет в сеть -- в офлайне
# это отказ, в оплаченном туннеле сюрприз.
os.environ.setdefault(
    "TIKTOKEN_CACHE_DIR", str(resources.files("trimitdown") / "tiktoken_cache")
)

TOKENS_PER_UNIT_ESTIMATE = 2250  # midpoint of the documented 1500-3000 tokens/page vision-estimate
                                  # range (Anthropic docs) — used for the PDF/PPTX before/after
                                  # comparison only. The frontend never renders a negative saving:
                                  # if a dense page's extracted text still exceeds this estimate,
                                  # it shows the raw result-token count with no percentage.

_encoding = None


class ConversionError(Exception):
    """Документ не удалось сконвертировать.

    Своё исключение, а не HTTPException: ядро не знает про HTTP. Веб-слой ловит
    его и переводит в 422, CLI -- в ненулевой код возврата.
    """


@dataclass(frozen=True)
class ConversionResult:
    text: str
    tokens_after: int | None
    tokens_before: int | None
    unit: str | None
    units: int | None


def _get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


def safe_stem(name: str) -> str:
    # Untrusted filenames may carry either separator regardless of host OS --
    # this same function sanitizes uploads on the Linux-hosted Docker server
    # and on the Windows/macOS desktop app. Path().stem's separator and root
    # parsing differ by platform (Windows treats "\" as a separator and
    # collapses a leading "///" into a UNC-style prefix; POSIX does neither),
    # so a name built from Path() here would sanitize differently depending
    # on which OS the server happens to run on. Reduce explicitly instead.
    last = re.split(r"[/\\]", name)[-1]
    stem = last.rsplit(".", 1)[0]
    stem = re.sub(r"[^\w\-. ]", "_", stem, flags=re.UNICODE).strip()
    return stem or "file"


def _count_pdf_pages(path: Path) -> int:
    with open(path, "rb") as f:
        return len(list(PDFPage.get_pages(f)))


def _count_pptx_slides(path: Path) -> int:
    return len(Presentation(path).slides)


def _estimate_before_tokens(suffix: str, path: str) -> tuple[int | None, str | None, int | None]:
    try:
        if suffix == ".pdf":
            units = _count_pdf_pages(Path(path))
            return units * TOKENS_PER_UNIT_ESTIMATE, "page", units
        if suffix == ".pptx":
            units = _count_pptx_slides(Path(path))
            return units * TOKENS_PER_UNIT_ESTIMATE, "slide", units
    except Exception:
        pass
    return None, None, None


def convert_path(path: Path | str) -> ConversionResult:
    """Сконвертировать файл на диске. Синхронно: асинхронность -- забота веб-слоя."""
    path = Path(path)
    suffix = path.suffix.lower()

    try:
        with open(path, "rb") as f:
            head = f.read(1024)

        # PDFs take our own extractor: markitdown's PDF converter glues words
        # together, invents tables out of prose, and drops real ones. No fallback
        # to markitdown here — both sit on pdfminer, so a file that breaks one
        # breaks the other. This is a route, not a fallback: markitdown itself
        # dispatches by sniffing content, so an HTML/TXT file misnamed ".pdf"
        # used to convert fine through markitdown. Checking the %PDF magic bytes
        # keeps real PDFs on our path and hands everything else back to
        # markitdown's own sniffing, exactly as before.
        #
        # This check has now been written wrong twice. `data[:5] == b"%PDF"` was
        # always False (5-byte slice, 4-byte literal) and made the branch a
        # silent no-op. `data[:4] == b"%PDF"` looks right but anchors the marker
        # at byte 0 — real PDFs can have a leading \r\n or junk before the header
        # (measured: 2 of 719 real files, one offset by 2 bytes, one by 135) and
        # pdfplumber parses both fine. Anchoring routed them to markitdown, which
        # is exactly the fallback this comment forbids. pdfminer itself scans for
        # the marker rather than anchoring, which is why those files open at all
        # — so scan a window instead of anchoring at byte 0.
        if suffix == ".pdf" and head.find(b"%PDF") != -1:
            text = pdf_to_markdown(str(path))
        else:
            text = md.convert(str(path)).text_content
    except Exception as e:
        raise ConversionError(str(e)) from e

    before, unit, units = _estimate_before_tokens(suffix, str(path))

    # Token count is a non-essential stat — the converted document must always be
    # returned. tiktoken can fail in a packaged build (e.g. the tiktoken_ext
    # encoding-constructor plugin not bundled), and an unguarded call there turned
    # every local-mode conversion into a 500. Degrade to a null count instead.
    try:
        after = count_tokens(text)
    except Exception:
        after = None

    return ConversionResult(
        text=text, tokens_after=after, tokens_before=before, unit=unit, units=units
    )


def convert_bytes(data: bytes, suffix: str) -> ConversionResult:
    """Сконвертировать содержимое в памяти.

    Существует ради веб-слоя, где вход -- UploadFile, а не путь. Временный файл
    нужен потому, что и markitdown, и наш движок работают с путями.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return convert_path(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
