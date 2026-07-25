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


def test_unreadable_file_reports_cleanly(tmp_path):
    # A directory won't do here: _run_convert's path.is_file() gate rejects it
    # before convert_path (and its now-fixed open()-inside-try) is ever reached.
    # To exercise that code path we need a real file that passes is_file() but
    # still fails to open for reading. msvcrt.locking (Windows) takes an
    # exclusive byte-range lock from this test process; the CLI subprocess then
    # hits PermissionError on open(), same as a permission-denied or
    # locked-by-another-process file would in the field.
    import msvcrt

    locked = tmp_path / "locked.pdf"
    locked.write_bytes(b"%PDF-1.4 " + b"x" * 2000)

    with open(locked, "r+b") as f:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 2000)
        try:
            result = run(["convert", str(locked)])
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 2000)

    assert result.returncode != 0
    assert "Traceback" not in result.stderr


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
