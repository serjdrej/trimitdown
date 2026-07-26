"""CLI: единственный интерфейс pip/uvx-пакета. Только локальная конверсия."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdf_fixtures

CLI = [sys.executable, "-m", "trimitdown.cli"]


def run(args, **kw):
    return subprocess.run(CLI + args, capture_output=True, text=True, encoding="utf-8", **kw)


def test_convert_prints_markdown_to_stdout(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())

    result = run(["convert", str(pdf)])

    assert result.returncode == 0, result.stderr
    assert "|" in result.stdout


def test_successful_conversion_does_not_warn_about_ffmpeg(tmp_path):
    # markitdown тянет pydub, а тот на импорте предупреждает об отсутствии
    # ffmpeg. Аудио мы не конвертируем, зато пользователь CLI видит это в
    # каждом вызове и не может отличить шум от настоящей проблемы -- на NAS
    # предупреждение и было принято за ошибку.
    #
    # Первая версия требовала пустой stderr целиком, и это оказалось обещанием,
    # которого не сдержать: onnxruntime (приезжает с markitdown через magika)
    # печатает предупреждение о PCI-шине из нативного кода прямо в fd 2, мимо
    # модуля warnings, и зависит оно от железа -- на CI есть, на Windows нет.
    # Гасить его пришлось бы подменой файлового дескриптора на время импорта,
    # то есть ценой проглоченных настоящих ошибок импорта. Проверяем то, за что
    # отвечаем.
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())

    result = run(["convert", str(pdf), "-o", str(tmp_path / "doc.md")])

    assert result.returncode == 0
    assert "ffmpeg" not in result.stderr, f"вернулся шум pydub: {result.stderr!r}"


def test_output_flag_writes_a_file(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())
    out = tmp_path / "doc.md"

    result = run(["convert", str(pdf), "-o", str(out)])

    assert result.returncode == 0, result.stderr
    assert "|" in out.read_text(encoding="utf-8")
    assert result.stdout.strip() == ""      # с -o в stdout не дублируем


def test_stdin_requires_an_explicit_type(tmp_path):
    # Из потока расширение неоткуда взять, и угадывать нельзя: markitdown
    # диспетчеризует по содержимому, а наш PDF-путь -- по расширению.
    result = run(["convert", "-"], input="whatever")

    assert result.returncode != 0
    assert "--type" in result.stderr


def test_stdin_with_type_reports_bad_input_cleanly():
    # input="" даёт пустой поток; input=None унаследовал бы stdin процесса и
    # подвесил pytest. Пустой ввод -- невалидный PDF: важно, что процесс не падает
    # трейсбеком, а сообщает об ошибке и возвращает ненулевой код.
    result = run(["convert", "-", "--type", ".pdf"], input="")

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_failed_conversion_of_an_existing_file_reports_cleanly(tmp_path):
    # Второй путь отказа, отдельный от отсутствующего файла: файл существует и
    # проходит гейт path.is_file(), но конвертация падает. Срабатывает ветка
    # except ConversionError в файловом рукаве -- та, до которой
    # test_missing_file_reports_cleanly не доходит, потому что отсекается раньше.
    #
    # Первая версия этого теста брала файл, заблокированный через msvcrt, чтобы
    # воспроизвести именно permission denied. Она работала только на Windows, а
    # CI гоняется на ubuntu -- там импорт msvcrt превратил бы тест в ошибку.
    # Пропустить его нельзя: инвариант набора -- ноль скипов.
    #
    # Сигнатура %PDF валидна, поэтому маршрут уходит в наш экстрактор, а он на
    # обрубке спотыкается. Мусор с расширением .docx для этого не годится:
    # markitdown диспетчеризует по содержимому и вернёт текст вместо отказа
    # (проверено).
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 this is not a pdf")

    result = run(["convert", str(broken)])

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "broken.pdf" in result.stderr


def test_missing_file_reports_cleanly(tmp_path):
    result = run(["convert", str(tmp_path / "nope.pdf")])

    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "nope.pdf" in result.stderr


def test_version_matches_the_package():
    from trimitdown import __version__

    result = run(["--version"])

    assert result.returncode == 0
    assert __version__ in result.stdout


def test_cli_has_no_network_flags():
    # Решение владельца 2026-07-24: работа с внешним сервером -- это канал Docker,
    # а не режим CLI. Флаг, добавленный "на всякий случай", вернул бы сетевые
    # отказы в инструмент, который ценен именно локальностью.
    help_text = run(["convert", "--help"]).stdout
    assert "--server" not in help_text
