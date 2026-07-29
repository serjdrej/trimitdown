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


def test_type_without_a_leading_dot_still_reaches_the_pdf_engine(tmp_path):
    """A missing dot must not silently downgrade the conversion.

    Routing is by extension, and the PDF engine answers to ".pdf" exactly.
    Before this was normalised, `--type pdf` wrote a temp file with no
    extension, fell through to the stock converter, and returned the ruled
    table as loose lines -- no error, no warning, just the defect the engine
    exists to remove. Asserting on the table is the point: a weaker check that
    the command exited 0, or that some markdown came out, passes on exactly the
    broken behaviour this test was written for.
    """
    pdf = pdf_fixtures.ruled_table()

    def convert(type_argument):
        # subprocess.run directly, not the helper above: the document goes in as
        # bytes on stdin, and the helper fixes the streams to text.
        return subprocess.run(CLI + ["convert", "-", "--type", type_argument],
                              input=pdf, capture_output=True)

    dotted = convert(".pdf")
    bare = convert("pdf")

    assert dotted.returncode == 0 and bare.returncode == 0
    assert b"| Header A | Header B |" in dotted.stdout
    assert bare.stdout == dotted.stdout, \
        "the spelling of --type changed the conversion, not just the argument"
