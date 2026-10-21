"""The non-PDF path of trimitdown.convert: office formats, HTML and plain text.

Fixtures are written by the tests (python-docx, openpyxl, or bytes by hand);
no document is committed. These tests RUN in CI -- requirements-dev.txt installs
the `office` extra on purpose -- because the suite asserts zero skips.

Every test says what it would miss if weakened; each was checked by breaking the
code it guards and watching it fail (the list is in the 0.3.0 report).
"""
import sys
import zipfile
from pathlib import Path

import pytest

from trimitdown import convert as pure
from trimitdown.convert import ConversionError, convert_path


# --------------------------------------------------------------------------
# Office formats through anydoc
# --------------------------------------------------------------------------

def _docx_with_table(path: Path) -> Path:
    import docx

    document = docx.Document()
    document.add_heading("Отчёт", 1)
    document.add_paragraph("Intro text")
    table = document.add_table(rows=3, cols=2)
    for row, (left, right) in enumerate([("Item", "Qty"), ("Яблоко", "3"), ("Pear", "5")]):
        table.cell(row, 0).text = left
        table.cell(row, 1).text = right
    document.save(str(path))
    return path


def test_docx_table_becomes_a_markdown_table(tmp_path):
    # A table that arrives as running prose, or as raw XML, is the failure the
    # office extra exists to prevent. Asserting the whole table block, not the
    # word "Item", is what catches a converter that keeps the cells but loses
    # the grid; the Cyrillic cell catches an encoding loss on the way.
    result = convert_path(_docx_with_table(tmp_path / "t.docx"))

    assert "| Item | Qty |\n| --- | --- |\n| Яблоко | 3 |\n| Pear | 5 |" in result.text
    assert result.text.startswith("# Отчёт")


def test_xlsx_gives_one_section_per_sheet(tmp_path):
    # Two sheets, not one: a converter that reads only the active sheet still
    # produces a table, and every other test would stay green.
    import openpyxl

    workbook = openpyxl.Workbook()
    first = workbook.active
    first.title = "Alpha"
    first.append(["a", "b"])
    first.append([1, 2])
    second = workbook.create_sheet("Бета")
    second.append(["x", "y"])
    second.append(["ю", 9])
    path = tmp_path / "t.xlsx"
    workbook.save(str(path))

    text = convert_path(path).text

    assert "## Alpha\n\n| a | b |\n| --- | --- |\n| 1 | 2 |" in text
    assert "## Бета\n\n| x | y |\n| --- | --- |\n| ю | 9 |" in text


def test_office_file_misnamed_pdf_still_converts(tmp_path):
    # AGENTS.md: a file misnamed .pdf must still convert. A DOCX has no %PDF
    # marker, so it leaves the PDF route; anydoc then reads it by content. If
    # the suffix were trusted again this would be refused as a broken PDF.
    docx_path = _docx_with_table(tmp_path / "t.docx")
    disguised = tmp_path / "report.pdf"
    disguised.write_bytes(docx_path.read_bytes())

    assert "| Яблоко | 3 |" in convert_path(disguised).text


def test_anydoc_is_called_with_ocr_reject_and_no_credentials(tmp_path, monkeypatch):
    # anydoc's "hosted" mode uploads the WHOLE document to Firecrawl, and an
    # api_key or api_url makes that happen without a visible switch. Nothing may
    # pass either. Asserting the exact call -- positional path, one keyword --
    # fails on any added key, on ocr="hosted", and on a dropped ocr (which would
    # fall back to anydoc's default). Weakening this to `kwargs["ocr"] == "reject"`
    # would let an api_key ride along unnoticed.
    import anydoc

    calls = []

    def recording(*args, **kwargs):
        calls.append((args, kwargs))
        return "# stub\n"

    monkeypatch.setattr(anydoc, "to_markdown", recording)
    doc = tmp_path / "x.docx"
    doc.write_bytes(b"PK")

    assert convert_path(doc).text == "# stub\n"
    assert calls == [((str(doc),), {"ocr": "reject"})]


def test_anydoc_errors_become_short_conversion_errors(tmp_path, monkeypatch):
    # Each anydoc failure kind must surface as ConversionError (the CLI turns it
    # into a one-line message and a non-zero exit; a raw anydoc exception would
    # be a traceback) and the message must name the problem, not repeat a class
    # name. Checking the fragment per kind catches a mapping collapsed into one
    # generic line. A loop rather than a parametrized test: the pre-commit guard
    # reads a decorator line as an email address.
    import anydoc

    cases = [
        ("EncryptedError", "password-protected"),
        ("NeedsOcrError", "needs OCR"),
        ("ResourceLimitError", "safety limit"),
        ("MalformedError", "damaged"),
        ("MissingPartError", "incomplete"),
        ("UnsupportedError", "unsupported file type"),
        ("ConvertError", "could not be converted"),
    ]
    doc = tmp_path / "x.docx"
    doc.write_bytes(b"PK")

    for error_name, fragment in cases:
        def refuse(*args, _name=error_name, **kwargs):
            raise getattr(anydoc, _name)("detail from anydoc")

        monkeypatch.setattr(anydoc, "to_markdown", refuse)

        with pytest.raises(ConversionError) as caught:
            convert_path(doc)

        assert fragment in str(caught.value), error_name
        assert "Traceback" not in str(caught.value), error_name


def test_unsupported_file_is_a_conversion_error_naming_the_supported_formats(tmp_path):
    # Real anydoc, no stub: JSON, MSG, ZIP, images and audio were accepted by
    # markitdown and are dropped in 0.3. The refusal has to be loud and say
    # what is accepted instead of silently returning nothing.
    unknown = tmp_path / "data.json"
    unknown.write_text('{"a": 1}', encoding="utf-8")

    with pytest.raises(ConversionError) as caught:
        convert_path(unknown)

    assert "unsupported file type" in str(caught.value)
    assert "DOCX" in str(caught.value)


def test_damaged_office_file_is_a_conversion_error(tmp_path):
    # A real failure from the engine rather than a stub: a "DOCX" that is not a
    # zip. The stubs above prove the mapping; this proves anydoc really raises
    # something the mapping catches, so a renamed base class would show here.
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"this is not a zip archive")

    with pytest.raises(ConversionError, match="damaged"):
        convert_path(broken)

    hollow = tmp_path / "hollow.docx"
    with zipfile.ZipFile(hollow, "w") as archive:
        archive.writestr("unrelated.txt", "x")

    with pytest.raises(ConversionError, match="incomplete"):
        convert_path(hollow)


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def test_html_drops_script_and_style_and_keeps_the_heading(tmp_path):
    # The script text is the whole point: markdownify alone would print it as
    # prose. Asserting the heading too proves the page was converted rather than
    # blanked.
    page = tmp_path / "page.html"
    page.write_text(
        "<html><head><style>p { color: red }</style><title>T</title></head>"
        "<body><h1>Heading</h1><script>var secret = 1;</script><p>Body text</p></body></html>",
        encoding="utf-8",
    )

    text = convert_path(page).text

    assert text == "# Heading\n\nBody text"
    assert "secret" not in text and "color" not in text


def test_script_and_style_are_dropped_by_us_not_only_by_markdownify(tmp_path, monkeypatch):
    # The installed markdownify already ignores <script> and <style>, so the
    # test above stays green even if our own removal is deleted -- the removal
    # is a guard against a markdownify that does not (the floor is 1.2, not the
    # latest). Disabling markdownify's own handlers here makes ours the only
    # defence; deleting the removal in _html_to_markdown must fail this test.
    import markdownify

    monkeypatch.setattr(markdownify.MarkdownConverter, "convert_script", lambda self, el, text, *a, **k: text)
    monkeypatch.setattr(markdownify.MarkdownConverter, "convert_style", lambda self, el, text, *a, **k: text)
    page = tmp_path / "page.html"
    page.write_text(
        "<body><h1>Heading</h1><script>var secret = 1;</script><style>p { color: red }</style><p>Body</p></body>",
        encoding="utf-8",
    )

    text = convert_path(page).text

    assert text == "# Heading\n\nBody"


def test_html_without_a_body_is_still_converted(tmp_path):
    # The whole document is converted when there is no <body>; html.parser keeps
    # fragments as they are.
    fragment = tmp_path / "fragment.htm"
    fragment.write_text("<h2>Only a fragment</h2><script>x()</script>", encoding="utf-8")

    assert convert_path(fragment).text == "## Only a fragment"


def test_html_links_and_images_are_cleaned(tmp_path):
    # A javascript: or mailto: target is noise in pasted text and the words must
    # stay; an inline data: image is thousands of tokens of base64. Dropping
    # either cleanup leaves the raw target in the output.
    page = tmp_path / "page.html"
    page.write_text(
        '<body><p><a href="javascript:run()">click me</a> '
        '<a href="mailto:team">write</a> '
        '<a href="https://example.test/x">site</a> '
        '<a href="relative.html">rel</a></p>'
        '<img src="data:image/png;base64,AAAABBBBCCCC" alt="logo"></body>',
        encoding="utf-8",
    )

    text = convert_path(page).text

    assert "click me" in text and "javascript" not in text
    assert "write" in text and "mailto" not in text
    assert "[site](https://example.test/x)" in text
    assert "[rel](relative.html)" in text
    assert "![logo](data:image/png;base64...)" in text
    assert "AAAABBBB" not in text


def test_html_meta_charset_is_honoured(tmp_path):
    # A Russian page in windows-1251 that declares itself. Decoding it as UTF-8
    # (or as cp1252, the fallback) turns the Cyrillic into replacement
    # characters; only reading the declaration gets it right.
    page = tmp_path / "ru.html"
    page.write_bytes(
        '<html><head><meta charset="windows-1251"></head><body><h1>Привет, мир</h1></body></html>'.encode("cp1251")
    )

    assert convert_path(page).text == "# Привет, мир"


def test_html_http_equiv_charset_is_honoured(tmp_path):
    page = tmp_path / "ru.html"
    page.write_bytes(
        (
            '<html><head><meta http-equiv="Content-Type" content="text/html; charset=koi8-r">'
            "</head><body><p>Привет</p></body></html>"
        ).encode("koi8-r")
    )

    assert convert_path(page).text == "Привет"


def test_html_utf8_bom_and_undeclared_utf8(tmp_path):
    bom = tmp_path / "bom.html"
    bom.write_bytes("﻿<h1>Привет</h1>".encode("utf-8"))
    plain = tmp_path / "plain.html"
    plain.write_bytes("<h1>Привет</h1>".encode("utf-8"))

    # The BOM must not survive as U+FEFF in the heading.
    assert convert_path(bom).text == "# Привет"
    assert convert_path(plain).text == "# Привет"


def test_html_undeclared_legacy_bytes_fall_back_to_cp1252(tmp_path):
    # HTML5's default for an undeclared page that is not valid UTF-8. Failing
    # here would refuse old Western pages; guessing Cyrillic would be a guess.
    page = tmp_path / "old.html"
    page.write_bytes("<p>caf\xe9</p>".encode("latin-1"))

    assert convert_path(page).text == "café"


def test_html_utf16_is_decoded_and_sniffed(tmp_path):
    # UTF-16 pages carry a BOM and NUL-interleaved ASCII, which a naive byte
    # sniff for "<html" cannot see. The suffix is neutral on purpose: the only
    # thing that can route this file to the HTML path is the sniff.
    page = tmp_path / "page.bin"
    page.write_bytes("<html><body><h1>Привет</h1></body></html>".encode("utf-16"))

    assert convert_path(page).text == "# Привет"


def test_html_is_recognised_by_content_whatever_the_suffix(tmp_path):
    page = tmp_path / "saved.dat"
    page.write_bytes(b"  \n<!DOCTYPE HTML PUBLIC><HTML><BODY><H1>Sniffed</H1></BODY></HTML>")

    assert convert_path(page).text == "# Sniffed"


def test_binary_header_containing_html_text_is_not_sniffed_as_html():
    # A zip or OLE header is full of NUL bytes; if "<html" appears in it by
    # chance (here: planted), the container must still go to anydoc. Without the
    # NUL guard this returns True.
    assert pure._sniffs_as_html(b"PK\x03\x04\x14\x00\x00\x00<html>") is False
    assert pure._sniffs_as_html(b"<html>") is True


def test_deeply_nested_html_degrades_to_plain_text(tmp_path, monkeypatch):
    # markdownify recurses; a page nested past the interpreter's limit raises
    # RecursionError. The text is more valuable than the markup, so it must
    # come back as plain text, not as a failed conversion.
    import markdownify

    def too_deep(self, soup):
        raise RecursionError

    monkeypatch.setattr(markdownify.MarkdownConverter, "convert_soup", too_deep)
    page = tmp_path / "deep.html"
    page.write_text("<body><div><p>still readable</p></div></body>", encoding="utf-8")

    assert convert_path(page).text == "still readable"


# --------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------

def test_txt_with_cyrillic_passes_through_unchanged(tmp_path):
    # markitdown passed .txt through; dropping it would be a silent regression.
    # Byte-for-byte equality, including the line break and the Cyrillic,
    # catches a converter that "improves" the text on the way.
    note = tmp_path / "note.txt"
    note.write_bytes("Привет, мир\nвторая строка\n".encode("utf-8"))

    assert convert_path(note).text == "Привет, мир\nвторая строка\n"


def test_md_passes_through_even_when_it_quotes_html(tmp_path):
    # A markdown file is markdown: it must not be sniffed into the HTML path and
    # re-rendered, which would reflow it.
    note = tmp_path / "note.md"
    note.write_bytes(b"# Title\n\nUse <html> sparingly.\n")

    assert convert_path(note).text == "# Title\n\nUse <html> sparingly.\n"


def test_txt_utf8_bom_is_stripped(tmp_path):
    note = tmp_path / "note.txt"
    note.write_bytes("﻿Привет".encode("utf-8"))

    assert convert_path(note).text == "Привет"


def test_txt_utf16_is_decoded(tmp_path):
    note = tmp_path / "note.txt"
    note.write_bytes("Привет".encode("utf-16"))

    assert convert_path(note).text == "Привет"


def test_txt_in_a_legacy_code_page_is_refused_not_guessed(tmp_path):
    # Cyrillic text saved as windows-1251 is not valid UTF-8. Decoding it with
    # any fallback would hand an LLM confident mojibake with no error; the
    # refusal names the remedy. If someone adds a guess, this fails.
    note = tmp_path / "old.txt"
    note.write_bytes("Привет".encode("cp1251"))

    with pytest.raises(ConversionError, match="not valid UTF-8"):
        convert_path(note)


def test_text_and_html_paths_do_not_import_anydoc(tmp_path):
    # Plain text and HTML are ours; anydoc is imported only for what needs it.
    # A stray top-level import would make the base-plus-markdownify install
    # fail on a .txt.
    import subprocess

    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")
    probe = (
        "import sys\n"
        "from trimitdown.convert import convert_path\n"
        f"convert_path({str(note)!r}); convert_path({str(page)!r})\n"
        "print('anydoc' in sys.modules)\n"
    )
    run = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=300)

    assert run.returncode == 0, run.stderr
    assert run.stdout.strip() == "False"


# --------------------------------------------------------------------------
# Through the CLI, the interface the package ships
# --------------------------------------------------------------------------

def _cli(*args):
    import subprocess

    return subprocess.run(
        [sys.executable, "-m", "trimitdown.cli", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )


def test_cli_converts_a_docx(tmp_path):
    # End to end in a fresh interpreter: the import of anydoc, the call and the
    # write to stdout. The stubs elsewhere cannot show that the shipped entry
    # point reaches the converter.
    result = _cli("convert", str(_docx_with_table(tmp_path / "t.docx")))

    assert result.returncode == 0, result.stderr
    assert "| Яблоко | 3 |" in result.stdout


def test_cli_reports_an_unsupported_file_in_one_line(tmp_path):
    unknown = tmp_path / "data.json"
    unknown.write_text("{}", encoding="utf-8")

    result = _cli("convert", str(unknown))

    assert result.returncode != 0
    assert "unsupported file type" in result.stderr
    assert "Traceback" not in result.stderr
