"""Чистый слой конверсии: без FastAPI, без HTTP, без архива."""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdf_fixtures
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


def test_count_tokens_uses_the_offline_cache():
    # Кэш едет в пакете как package data. Проверять только count_tokens(...) > 0
    # бесполезно: при неразрешённом пути tiktoken молча скачает BPE из сети, и
    # тест пройдёт везде, где есть интернет -- то есть на всех раннерах CI.
    # Поэтому утверждается сам факт, что каталог разрешился и файл на месте.
    import os

    from trimitdown import convert  # noqa: F401  -- импорт выставляет переменную

    cache_dir = Path(os.environ["TIKTOKEN_CACHE_DIR"])
    assert cache_dir.is_dir(), f"кэш не разрешился: {cache_dir}"
    assert any(cache_dir.iterdir()), f"кэш пуст: {cache_dir}"
    assert count_tokens("hello world") > 0


def test_pure_module_does_not_import_fastapi():
    # Инвариант границы слоёв. Ломается молча: FastAPI подтянется транзитивно и
    # CLI-пакет утяжелится на весь веб-стек, ничего при этом не сломав внешне.
    code = (
        "import sys, trimitdown.convert; "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
