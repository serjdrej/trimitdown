"""CLI: единственный интерфейс pip/uvx-пакета. Только локальная конверсия."""
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pdf_fixtures
import route_fixtures

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
    # Из потока расширение неоткуда взять, и угадывать нельзя: PDF-путь решает
    # по расширению, а текст и HTML читаются по нему же.
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
    # The header row of a markdown table, whatever the cell padding:
    # pdf-inspector writes |Header A|Header B|, the old engine wrote
    # | Header A | Header B |. The stock converter's loose lines match neither.
    assert re.search(rb"\|\s*Header A\s*\|\s*Header B\s*\|", dotted.stdout), dotted.stdout
    assert bare.stdout == dotted.stdout, \
        "the spelling of --type changed the conversion, not just the argument"


# --- 0.2: the routed PDF, review directories, assemble, render ------------------

def _mixed(tmp_path):
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(route_fixtures.mixed_route_document())
    return pdf


def test_a_routed_document_says_so_on_stderr(tmp_path):
    """Pages that did not come from pdf-inspector are never invisible.

    One line on stderr with the count per path; the markers are in the text.
    Fails if the summary is dropped (verified).
    """
    result = run(["convert", str(_mixed(tmp_path))])

    assert result.returncode == 0, result.stderr
    assert result.stderr.startswith("7 pages: 1 accept, 2 substitute, 2 scan, 1 corrupt, 1 blank")
    assert "[trimitdown: page 3 has no usable text layer (scan)]" in result.stdout
    assert "[trimitdown: page 4: OCR layer, not verified]" in result.stdout


def test_a_clean_document_converts_silently(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())
    result = run(["convert", str(pdf)])
    assert result.returncode == 0 and result.stderr == ""


def test_review_dir_without_tesseract_says_what_is_missing(tmp_path):
    """No Tesseract is a stated condition, not a silent one.

    Fails if the stderr line about pages without a candidate is dropped.
    """
    out = tmp_path / "review"
    result = run(["convert", str(_mixed(tmp_path)), "--review-dir", str(out),
                  "--tesseract", str(tmp_path / "no-such-tesseract")])

    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "3 need review" in result.stderr
    assert "2 pages go to review without a candidate (Tesseract was not found)" in result.stderr
    for name in ("manifest.json", "document.md", "REVIEW.md"):
        assert (out / name).is_file()


def test_review_dir_from_stdin(tmp_path):
    out = tmp_path / "review"
    result = subprocess.run(CLI + ["convert", "-", "--type", "pdf", "--review-dir", str(out),
                                   "--no-ocr"],
                            input=route_fixtures.mixed_route_document(), capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (out / "pages" / "p0003.png").is_file()


def test_review_dir_refuses_a_non_pdf(tmp_path):
    doc = tmp_path / "note.txt"
    doc.write_text("hello", encoding="utf-8")
    result = run(["convert", str(doc), "--review-dir", str(tmp_path / "review")])
    assert result.returncode == 2
    assert "PDF" in result.stderr


def test_assemble_round_trip(tmp_path):
    out = tmp_path / "review"
    assert run(["convert", str(_mixed(tmp_path)), "--review-dir", str(out), "--no-ocr",
                "--review-markers", "en"]).returncode == 0

    refused = run(["assemble", str(out)])
    assert refused.returncode == 1
    assert "[3, 4, 5]" in refused.stderr and "Traceback" not in refused.stderr

    (out / "reviewed" / "doc.txt").write_text(
        "=== page 3 ===\nthree\n=== page 4 ===\nfour\n=== page 5 ===\nfive\n", encoding="utf-8")
    done = tmp_path / "done.md"
    result = run(["assemble", str(out), "-o", str(done)])
    assert result.returncode == 0, result.stderr
    text = done.read_text(encoding="utf-8")
    assert "three\n" in text and "five\n" in text
    # Pages stay citable: one anchor per page, in order (0.2.0 dropped them all).
    assert re.findall(r"^<!-- page (\d+) -->$", text, re.M) == [str(n) for n in range(1, 8)]

    bare = tmp_path / "bare.md"
    assert run(["assemble", str(out), "-o", str(bare), "--no-page-anchors"]).returncode == 0
    assert "<!-- page" not in bare.read_text(encoding="utf-8")


def test_convert_page_anchors_marks_every_page(tmp_path):
    """Opt-in: the default stays byte-identical to pdf-inspector; with the flag
    each page is citable. Fails if the flag is ignored or leaks into the default."""
    pdf = _mixed(tmp_path)
    anchored = run(["convert", str(pdf), "--page-anchors"])
    plain = run(["convert", str(pdf)])

    assert anchored.returncode == 0 and plain.returncode == 0
    assert re.findall(r"^<!-- page (\d+) -->$", anchored.stdout, re.M) == [str(n) for n in range(1, 8)]
    assert "<!-- page" not in plain.stdout


def test_render_writes_page_images(tmp_path):
    result = run(["render", str(_mixed(tmp_path)), "--pages", "2,5", "-o", str(tmp_path / "img")])
    assert result.returncode == 0, result.stderr
    assert sorted(p.name for p in (tmp_path / "img").iterdir()) == ["p0002.png", "p0005.png"]


def test_render_refuses_a_page_outside_the_document(tmp_path):
    result = run(["render", str(_mixed(tmp_path)), "--pages", "9", "-o", str(tmp_path / "img")])
    assert result.returncode == 2
    assert "outside 1-7" in result.stderr
