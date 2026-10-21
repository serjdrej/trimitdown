"""Tracked changes and silent omissions in Word documents (trimitdown 0.3.1).

anydoc drops tracked changes, comments and headers without a word, and prints a
DOC or RTF with the deleted wording in place and no marks. trimitdown.office_inspect
looks at the file first; convert.py refuses, accepts or notes what it found.

This module is the portable half and runs in CI. Its evidence is of two kinds:

* The four RTF files in tests/data/office, made in Word 365 (synthetic text,
  author scrubbed). Word's own object model gave their counts:

      file          revisions        comments  header+footer  images
      legal.rtf     1 ins + 1 del    1         1 + 1          1
      revonly.rtf   1 ins + 1 del    0         0              0
      clean.rtf     0                0         0              0
      num.rtf       0                0         0              0

* DOCX and RTF built from raw text below, so that each case says exactly which
  construct it is about.

The Word-made DOCX, DOC and ODT of the same documents are NOT in this tree (the
pre-commit guard takes binary documents for a leak, and their text for a
contract); tests/test_office_word_fixtures.py runs against them from outside the
tree as part of the owner's pre-release gate.

Every test says what it would miss if weakened; each was checked by breaking the
code it guards (the list is in the 0.3.1 report).

Loops instead of parametrized tests: the pre-commit guard reads a decorator line
as an email address.
"""
import base64
import io
import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from trimitdown import office_inspect as oi
from trimitdown.convert import ConversionError, convert_bytes, convert_path

DATA = Path(__file__).parent / "data" / "office"

DELETED = "Этаудаление"
INSERTED = "Тетавставка"


def _rtf_fixture(name: str) -> Path:
    return DATA / f"{name}.rtf"


# --------------------------------------------------------------------------
# Raw-text documents
# --------------------------------------------------------------------------

_W = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Default Extension="png" ContentType="image/png"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-'
    'officedocument.wordprocessingml.document.main+xml"/></Types>'
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/></Relationships>'
)
_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
AUTHOR = 'w:author="A" w:date="2026-01-01T00:00:00Z"'
# A 1x1 PNG.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
PICTURE = (
    '<w:r><w:drawing><wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
    '<wp:extent cx="190500" cy="190500"/><wp:docPr id="1" name="Picture 1"/>'
    '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
    '<pic:nvPicPr><pic:cNvPr id="0" name="p.png"/><pic:cNvPicPr/></pic:nvPicPr>'
    '<pic:blipFill><a:blip r:embed="rId50"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
    '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="190500" cy="190500"/></a:xfrm>'
    '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
    '</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
)


def _para(*runs, ppr=""):
    return f"<w:p>{'<w:pPr>' + ppr + '</w:pPr>' if ppr else ''}{''.join(runs)}</w:p>"


def _run(text):
    return f'<w:r><w:t xml:space="preserve">{text}</w:t></w:r>'


def _deleted_run(text):
    return f'<w:r><w:delText xml:space="preserve">{text}</w:delText></w:r>'


def _ins(identifier, *runs, author=AUTHOR):
    return f'<w:ins w:id="{identifier}" {author}>{"".join(runs)}</w:ins>'


def _del(identifier, *runs, author=AUTHOR):
    return f'<w:del w:id="{identifier}" {author}>{"".join(runs)}</w:del>'


def _mark(kind, identifier, author=AUTHOR):
    return f'<w:rPr><w:{kind} w:id="{identifier}" {author}/></w:rPr>'


def _docx(body: str, parts: dict[str, tuple[str, str]] | None = None, picture: bool = False) -> bytes:
    """A DOCX around `body`; `parts` maps a part name to (relationship type, XML)."""
    parts = parts or {}
    relationships = "".join(
        f'<Relationship Id="rId{n}" Type="{_REL_TYPE}{kind}" Target="{name}"/>'
        for n, (name, (kind, _)) in enumerate(parts.items(), start=10)
    )
    if picture:
        relationships += (
            f'<Relationship Id="rId50" Type="{_REL_TYPE}image" Target="media/image1.png"/>'
        )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f"<w:document {_W}><w:body>{body}</w:body></w:document>",
        )
        archive.writestr(
            "word/_rels/document.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{relationships}</Relationships>",
        )
        for name, (_, xml) in parts.items():
            archive.writestr(f"word/{name}", f'<?xml version="1.0"?><w:root {_W}>{xml}</w:root>')
        if picture:
            archive.writestr("word/media/image1.png", PNG)
    return buffer.getvalue()


def _rtf(body: str) -> bytes:
    return ("{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Arial;}}" + body + "}").encode("latin-1")


def _counts(data: bytes, fmt: str = "docx") -> tuple[int, int]:
    found = oi.inspect(data, fmt)
    return found.insertions, found.deletions


def _revised_docx() -> bytes:
    """One deleted word and one inserted paragraph: the shape of revonly.docx."""
    return _docx(
        _para(_run("Стороны согласовали "), _del(1, _deleted_run(DELETED + " ")), _run("условие."))
        + _para(_ins(2, _run(INSERTED + " добавлено при рецензировании.")), ppr=_mark("ins", 3))
        + _para(_run("Конец"))
    )


def _accepted_docx() -> bytes:
    """The same document after Word's "accept all"."""
    return _docx(
        _para(_run("Стороны согласовали "), _run("условие."))
        + _para(_run(INSERTED + " добавлено при рецензировании."))
        + _para(_run("Конец"))
    )


def _full_docx(revised: bool = True) -> bytes:
    """Everything Word can add around the text: a header, a footer, a comment, an image."""
    body = (
        _para(_run("Заголовок"))
        + (_para(_run("Стороны "), _del(1, _deleted_run(DELETED + " ")), _run("согласовали."))
           + _para(_ins(2, _run(INSERTED)), ppr=_mark("ins", 3))
           if revised else _para(_run("Стороны согласовали.")))
        + _para(_run("Текст с "), '<w:commentRangeStart w:id="0"/>', _run("комментарием"),
                '<w:commentRangeEnd w:id="0"/>',
                '<w:r><w:commentReference w:id="0"/></w:r>')
        + _para(_run("Картинка:"))
        + _para(PICTURE)
        + _para(_run("Конец"))
    )
    parts = {
        "header1.xml": ("header", _para()),                          # empty, as Word writes them
        "header2.xml": ("header", _para(_run("Нюверхний колонтитул"))),
        "footer1.xml": ("footer", _para(_run("Ксиnижний колонтитул"))),
        "comments.xml": ("comments", f'<w:comment w:id="0" {AUTHOR}>{_para(_run("Мюкомментарий"))}</w:comment>'),
    }
    return _docx(body, parts, picture=True)


# --------------------------------------------------------------------------
# The decision: refuse, accept, note
# --------------------------------------------------------------------------

def test_unresolved_changes_are_refused_with_the_counts():
    # The point of the release: the Word formats printed a struck-out wording as
    # live text (DOC, RTF) or dropped it without a trace (DOCX). Asserting the
    # counts in the message, not only the refusal, proves the reader is told
    # what was found. Both RTF files, because `revonly` has only the changes and
    # `legal` has everything else Word can add around them; the DOCX is built.
    cases = [_rtf_fixture("legal"), _rtf_fixture("revonly")]
    for path in cases:
        with pytest.raises(ConversionError) as caught:
            convert_path(path)
        assert "unresolved tracked changes (1 insertion, 1 deletion)" in str(caught.value), path.name

    with pytest.raises(ConversionError) as caught:
        convert_bytes(_revised_docx(), ".docx")
    assert "unresolved tracked changes (1 insertion, 1 deletion)" in str(caught.value)


def test_clean_documents_convert_without_a_note():
    # Same text with the changes accepted in Word. Weakening the refusal to
    # "any revision marks in the file" (or counting formatting) would refuse
    # these; a note printed for nothing would show in the first line.
    results = [convert_path(_rtf_fixture("clean")), convert_bytes(_accepted_docx(), ".docx")]
    for result in results:
        assert not result.text.startswith("<!--")
        assert result.report["tracked_changes"] == {
            "present": False, "insertions": 0, "deletions": 0, "accepted": False,
        }
        assert result.report["omitted"] == {"headers_footers": 0, "comments": 0, "images": 0}


def test_accept_changes_prints_the_accepted_text_of_a_docx():
    # --accept-changes is only worth having if the output is the accepted
    # reading: the inserted wording in, the deleted one out. Asserting both
    # sides catches an implementation that merely stops refusing (the DOC/RTF
    # output would contain the deleted word).
    accepted = convert_bytes(_revised_docx(), ".docx", accept_changes=True)

    assert INSERTED in accepted.text
    assert DELETED not in accepted.text


def test_accepted_docx_equals_the_same_document_accepted_in_word():
    # The pair mirrors revonly.docx / clean.docx. Equal to the character, after
    # the one note line, means anydoc's DOCX reading IS "accept all" for this
    # shape; a difference would be a defect to name.
    accepted = convert_bytes(_revised_docx(), ".docx", accept_changes=True)
    clean = convert_bytes(_accepted_docx(), ".docx")

    note, _, rest = accepted.text.partition("\n\n")
    assert note == "<!-- trimitdown: accepted 1 insertion, 1 deletion -->"
    assert rest == clean.text


def test_accept_changes_still_refuses_rtf():
    # Only DOCX has an accepted reading to hand over. If the flag opened RTF
    # (or DOC), the deleted word would be printed live under a note saying the
    # changes were accepted -- the exact lie this release removes.
    for name in ("legal", "revonly"):
        with pytest.raises(ConversionError) as caught:
            convert_path(_rtf_fixture(name), accept_changes=True)
        message = str(caught.value)
        assert "cannot repair that for this format" in message, name
        assert "as DOCX" in message, name


def test_accept_changes_is_off_by_default_in_the_python_api():
    # The door the web layer and skills use: refusal unless asked.
    data = _revised_docx()

    assert INSERTED in convert_bytes(data, ".docx", accept_changes=True).text
    with pytest.raises(ConversionError):
        convert_bytes(data, ".docx")


def test_omission_line_and_report_for_a_docx_with_everything_around_the_text():
    # The exact line, not a substring: it is what a reader sees first, and the
    # "only the non-zero parts" rule shows in what is missing from it. Two
    # header/footer parts carry text; the empty header is not counted.
    result = convert_bytes(_full_docx(), ".docx", accept_changes=True)

    first = result.text.split("\n", 1)[0]
    assert first == (
        "<!-- trimitdown: accepted 1 insertion, 1 deletion; "
        "omitted 2 header/footer parts, 1 comment, 1 image -->"
    )
    assert result.report == {
        "schema": 1,
        "format": "docx",
        "tracked_changes": {"present": True, "insertions": 1, "deletions": 1, "accepted": True},
        "omitted": {"headers_footers": 2, "comments": 1, "images": 1},
    }
    # The marker words really are gone from the text, so the line is not
    # decoration over an output that kept them.
    for word in ("Мюкомментарий", "Нюверхний", "Ксиnижний", DELETED):
        assert word not in result.text, word


def test_omission_line_without_changes_names_only_what_is_omitted():
    # "Only the non-zero parts": with nothing accepted the line starts at
    # "omitted", and a zero is never written out.
    result = convert_bytes(_full_docx(revised=False), ".docx")

    assert result.text.split("\n", 1)[0] == (
        "<!-- trimitdown: omitted 2 header/footer parts, 1 comment, 1 image -->"
    )


def _legal_rtf_without_revision_marks(tmp_path: Path) -> Path:
    """legal.rtf with the revision flags switched off, nothing else touched.

    Word's "accept" would also delete the struck-out word; here it stays as live
    text, which does not matter: the point is an RTF that carries a comment,
    headers, footers and an image but no tracked changes.
    """
    patched, n = re.subn(
        rb"\\(deleted|revised)(?![a-z0-9])", rb"\\\g<1>0", _rtf_fixture("legal").read_bytes()
    )
    assert n == 3  # one deleted run, two revised ones (text and paragraph mark)
    target = tmp_path / "legal-flat.rtf"
    target.write_bytes(patched)
    return target


def test_omissions_in_the_word_made_rtf_match_words_numbers(tmp_path):
    # Word counted 1 + 1 header/footer, 1 comment, 1 image in this file. A reader
    # that counted the empty header groups Word also writes would say more than
    # 2; one that forgot the \annotation group would say 0 comments.
    result = convert_path(_legal_rtf_without_revision_marks(tmp_path))

    assert result.report["omitted"] == {"headers_footers": 2, "comments": 1, "images": 1}
    assert result.report["tracked_changes"]["present"] is False
    assert result.text.startswith(
        "<!-- trimitdown: omitted 2 header/footer parts, 1 comment, 1 image -->\n\n"
    )


def test_no_omission_line_on_clean_and_numbered_rtf():
    # "Nothing when there is nothing": a note on every file would be noise that
    # trains the reader to skip it. num has lists, clean has a footnote and a
    # table -- the things that ARE carried must not count as omitted.
    for name in ("clean", "num"):
        assert "trimitdown:" not in convert_path(_rtf_fixture(name)).text, name


def test_word_numbering_is_printed_exactly_as_word_shows_it():
    # What made anydoc the choice over markitdown, which rewrote 1.1. as a
    # nested 1. and restarted the start-at-5 list at 1. Word shows
    # 1. 1.1. 1.2. 1.2.1. 2. 2.1. / 1. 2. 3. / 5. 6.
    text = convert_path(_rtf_fixture("num")).text

    for line in (
        "1. Предмет Альфа",
        "- 1.1. Обязанность Бета",
        "- 1.2. Обязанность Гамма",
        "- 1.2.1. Подпункт Дельта",
        "2. Цена Эпсилон",
        "- 2.1. Порядок оплаты Зета",
        "1. Первый Эта\n2. Второй Тета\n3. Третий Йота",
        "5. Пятый Каппа\n6. Шестой Лямбда",
    ):
        assert line in text, line


def test_footnotes_and_vertical_merges_survive():
    # Pinned together with the numbering: these are the other things anydoc gets
    # right, and the new layer must not disturb them. The merged cell is the
    # empty one under "Поставщик".
    text = convert_path(_rtf_fixture("clean")).text

    assert "Йотаосновной[^1]" in text
    assert "[^1]: Каппасноска текст сноски" in text
    assert "|  | Передать документы Пиячейка | 5 дней |" in text


def test_inspection_failure_does_not_print_the_document_unchecked(monkeypatch):
    # anydoc can read a file this module cannot examine. Printing it anyway is
    # the silent failure the layer exists to prevent, so the answer is a refusal
    # that says why. Letting InspectionFailed pass as "nothing found" would make
    # every one of the tests above green and this one red.
    def cannot(data, fmt):
        raise oi.InspectionFailed("test: no")

    monkeypatch.setattr(oi, "inspect", cannot)

    with pytest.raises(ConversionError, match="could not be checked.*not printed unchecked"):
        convert_bytes(_accepted_docx(), ".docx")


def test_a_file_anydoc_cannot_read_gets_anydocs_message_not_ours(tmp_path):
    # The inspection fails on this file too; the reader should be told what is
    # wrong with the file, not that a check was skipped.
    broken = tmp_path / "broken.docx"
    broken.write_bytes(b"this is not a zip archive")

    with pytest.raises(ConversionError, match="damaged"):
        convert_path(broken)


def test_other_formats_report_their_format_and_nothing_about_changes(tmp_path):
    # tracked_changes/omitted exist only for the formats that are inspected
    # (DOCX, DOC, RTF). A report that claimed "0 comments" for a text file
    # would be a claim nobody checked.
    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<h1>x</h1>", encoding="utf-8")

    assert convert_path(note).report == {"schema": 1, "format": "txt"}
    assert convert_path(page).report == {"schema": 1, "format": "html"}


def test_odt_content_is_refused_whatever_the_file_is_called(tmp_path):
    # ODT is refused until anydoc reads its nested numbering and comments
    # correctly. The refusal follows the content: an ODT given another name must
    # not slip past it. Built here as a bare package with the ODT mimetype --
    # the Word-saved ODT files are in the pre-release set.
    odt = tmp_path / "report.docx"
    with zipfile.ZipFile(odt, "w") as archive:
        archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        archive.writestr(
            "content.xml",
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"'
            ' xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0">'
            "<office:body><office:text><text:p>x</text:p></office:text></office:body>"
            "</office:document-content>",
        )

    with pytest.raises(ConversionError) as caught:
        convert_path(odt)
    assert "ODT is not converted" in str(caught.value)
    assert "numbering" in str(caught.value) and "comments" in str(caught.value)


def test_a_docx_named_odt_is_not_refused_for_its_name(tmp_path):
    # The other direction of the same rule.
    docx_named_odt = tmp_path / "report.odt"
    docx_named_odt.write_bytes(_accepted_docx())

    assert "условие" in convert_path(docx_named_odt).text


# --------------------------------------------------------------------------
# DOCX: what counts, built from raw XML
# --------------------------------------------------------------------------

def test_docx_counts_an_insertion_and_its_paragraph_mark_as_one():
    # Word's Revisions.Count says 1 for "text typed, then Enter". Counting the
    # <w:ins> in the paragraph properties separately would give 2 and disagree
    # with Word on the very fixture this release was measured on.
    body = _para(_run("kept")) + _para(_ins(1, _run("new")), ppr=_mark("ins", 2))

    assert _counts(_docx(body)) == (1, 0)


def test_docx_adjacent_insertions_by_one_author_are_one_but_separated_ones_are_two():
    # Word splits one typed sentence into several <w:ins> when the formatting
    # changes mid-way; they are one revision. Unchanged text between two
    # insertions makes them two. Checks both directions of the merge rule.
    adjacent = _para(_ins(1, _run("a ")), _ins(2, _run("b ")), _ins(3, _run("c")))
    separated = _para(_ins(1, _run("a ")), _run("kept "), _ins(2, _run("b")))

    assert _counts(_docx(adjacent)) == (1, 0)
    assert _counts(_docx(separated)) == (2, 0)


def test_docx_changes_by_different_authors_are_counted_apart():
    other = 'w:author="B" w:date="2026-01-01T00:00:00Z"'
    body = _para(_ins(1, _run("a ")), _ins(2, _run("b"), author=other))

    assert _counts(_docx(body)) == (2, 0)


def test_docx_moves_are_a_deletion_and_an_insertion():
    # The moved text disappears from where it was and appears where it went;
    # "accept all" keeps only the second, and anydoc agrees.
    body = (
        _para(_run("A "), f'<w:moveFrom w:id="1" {AUTHOR}>{_run("moved ")}</w:moveFrom>', _run("B"))
        + _para(f'<w:moveTo w:id="2" {AUTHOR}>{_run("moved ")}</w:moveTo>', _run("C"))
    )
    data = _docx(body)

    assert _counts(data) == (1, 1)
    assert convert_bytes(data, ".docx", accept_changes=True).text.count("moved") == 1


def test_docx_formatting_only_changes_are_not_tracked_changes():
    # Decision, stated in office_inspect: a bold-to-regular change leaves every
    # character as it was, so it neither needs a refusal nor changes what
    # "accepted" means. If these were counted, a document with one reformatted
    # word would be refused over nothing.
    body = _para(
        f'<w:r><w:rPr><w:b/><w:rPrChange w:id="1" {AUTHOR}><w:rPr/></w:rPrChange></w:rPr>'
        "<w:t>bold now</w:t></w:r>",
        ppr=f'<w:jc w:val="center"/><w:pPrChange w:id="2" {AUTHOR}><w:pPr/></w:pPrChange>',
    )

    assert _counts(_docx(body)) == (0, 0)
    assert "bold now" in convert_bytes(_docx(body), ".docx").text


def test_docx_counts_changes_in_footnotes_but_not_in_comments():
    # Footnotes are printed, so a change in one reaches the reader. A comment is
    # omitted whole, so a change inside it cannot.
    footnotes = _para(_del(7, _deleted_run("gone")), _ins(8, _run("kept")))
    comment = f'<w:comment w:id="0">{_para(_ins(9, _run("inside a comment")))}</w:comment>'
    body = _para(_run("text"))

    with_footnote = _docx(body, {"footnotes.xml": ("footnotes", footnotes)})
    with_comment = _docx(body, {"comments.xml": ("comments", comment)})

    assert _counts(with_footnote) == (1, 1)
    assert _counts(with_comment) == (0, 0)
    assert oi.inspect(with_comment, "docx").comments == 1


def test_docx_header_and_footer_parts_count_only_when_they_carry_text():
    # Word writes empty first-page and even-page headers into almost every file;
    # counting them would put a note on every document. A page number counts.
    parts = {
        "header1.xml": ("header", _para()),                 # empty
        "header2.xml": ("header", _para(_run("Верхний"))),
        "footer1.xml": ("footer", _para(_run("  "))),       # blanks only
        "footer2.xml": ("footer", _para(_run("1"))),        # a page number
    }

    assert oi.inspect(_docx(_para(_run("x")), parts), "docx").headers_footers == 2


def test_docx_shared_header_part_is_counted_once():
    # Several relationships to one part (sections that share a header) are one
    # part; counting relationships would multiply a single header.
    data = _docx(_para(_run("x")), {"header1.xml": ("header", _para(_run("Верхний")))})
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    files["word/_rels/document.xml.rels"] = files["word/_rels/document.xml.rels"].replace(
        b"</Relationships>",
        f'<Relationship Id="rId99" Type="{_REL_TYPE}header" Target="header1.xml"/></Relationships>'.encode(),
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    assert oi.inspect(buffer.getvalue(), "docx").headers_footers == 1


def test_docx_things_that_anydoc_would_not_accept_faithfully_block_the_flag():
    # Each of these was measured: anydoc's output differs from Word's "accept
    # all" for the construct. The flag must refuse them, not print a document
    # that only looks accepted. (Checked against anydoc: a deleted row stays as
    # an empty row; a deleted numbered paragraph stays as an empty item that
    # swallows the next one; a deleted paragraph break does not join.)
    row_cells = "".join(f"<w:tc><w:p>{_run(t)}</w:p></w:tc>" for t in ("k1", "k2"))
    deleted_row = (
        "<w:tbl><w:tblGrid><w:gridCol w:w=\"3000\"/><w:gridCol w:w=\"3000\"/></w:tblGrid>"
        f"<w:tr>{row_cells}</w:tr>"
        f'<w:tr><w:trPr><w:del w:id="1" {AUTHOR}/></w:trPr>'
        f"<w:tc><w:p>{_del(2, _deleted_run('x'))}</w:p></w:tc>"
        f"<w:tc><w:p>{_del(3, _deleted_run('y'))}</w:p></w:tc></w:tr></w:tbl>"
    ) + _para(_run("after"))
    joined = _para(_run("first "), ppr=_mark("del", 1)) + _para(_run("second"))
    numbered = _para(
        _del(1, _deleted_run("gone")),
        ppr='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>' + _mark("del", 2),
    )

    for label, body in (("row", deleted_row), ("join", joined), ("list item", numbered)):
        found = oi.inspect(_docx(body), "docx")
        assert found.deletions >= 1 and found.accept_blockers, label
        with pytest.raises(ConversionError, match="cannot apply faithfully"):
            convert_bytes(_docx(body), ".docx", accept_changes=True)


def test_docx_a_wholly_deleted_plain_paragraph_does_not_block_the_flag():
    # The other side of the rule above, so that it is not "any deleted mark
    # blocks": a plain paragraph deleted together with its mark leaves nothing
    # in anydoc's output, and the flag may proceed. Without this the flag would
    # refuse the most common deletion there is.
    body = (
        _para(_run("keep one"))
        + _para(_del(1, _deleted_run("gone")), ppr=_mark("del", 2))
        + _para(_run("keep two"))
    )

    found = oi.inspect(_docx(body), "docx")
    assert (found.insertions, found.deletions, found.accept_blockers) == (0, 1, ())
    assert "keep one\n\nkeep two" in convert_bytes(_docx(body), ".docx", accept_changes=True).text


def test_docx_with_an_entity_declaration_is_not_parsed():
    # A DOCX part has no business declaring entities. Refusing outright is the
    # defence against entity expansion; the conversion then reports it.
    with zipfile.ZipFile(io.BytesIO(_docx(_para(_run("x"))))) as source:
        files = {name: source.read(name) for name in source.namelist()}
    files["word/document.xml"] = files["word/document.xml"].replace(
        b"<w:document", b'<!DOCTYPE d [<!ENTITY e "x">]><w:document', 1
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)

    with pytest.raises(oi.InspectionFailed, match="entities"):
        oi.inspect(buffer.getvalue(), "docx")


# --------------------------------------------------------------------------
# RTF: what counts, built from raw text
# --------------------------------------------------------------------------

def test_rtf_deleted_and_revised_runs_are_counted_with_their_paragraph_mark():
    body = (
        "{\\pard kept {\\deleted\\revauthdel1 struck}\\par}"
        "{\\pard {\\revised\\revauth1 typed}{\\revised\\revauth1 \\par}}"
    )

    assert _counts(_rtf(body), "rtf") == (1, 1)


def test_rtf_unchanged_text_between_two_revised_runs_makes_two():
    body = "{\\pard {\\revised\\revauth1 a} kept {\\revised\\revauth1 b}\\par}"

    assert _counts(_rtf(body), "rtf") == (2, 0)


def test_rtf_zero_parameter_switches_a_flag_off():
    # \deleted0 is "not deleted"; reading any \deleted as on would refuse
    # documents whose revision flags were reset.
    body = "{\\pard \\deleted text \\deleted0 more\\par}"

    assert _counts(_rtf(body), "rtf") == (0, 1)
    assert _counts(_rtf("{\\pard \\deleted0 text\\par}"), "rtf") == (0, 0)


def test_rtf_header_destinations_only_not_the_distance_words():
    # \headery708 is a distance, not a header; counting it would make every
    # file carry a header. Only a group that opens with \header* and holds
    # printable text counts; a field's result is text, its instruction is not.
    body = (
        "\\sectd\\headery708\\footery708"
        "{\\headerl \\pard\\par}"            # empty
        "{\\headerr \\pard Top\\par}"        # text
        "{\\footerr \\pard {\\field{\\*\\fldinst PAGE}{\\fldrslt 3}}\\par}"
        "\\pard body\\par"
    )

    assert oi.inspect(_rtf(body), "rtf").headers_footers == 2


def test_rtf_a_header_holding_only_a_field_instruction_is_empty():
    # The instruction ("PAGE") is not what a reader sees; with no result there
    # is no text. Counting it would report an omission that is not one.
    body = "{\\footerr \\pard {\\field{\\*\\fldinst PAGE}}\\par}"

    assert oi.inspect(_rtf(body), "rtf").headers_footers == 0


def test_rtf_comments_pictures_and_binary_data_do_not_confuse_the_scan():
    # An \annotation group is a comment and its text is not document text; a
    # \bin run is raw bytes that may contain braces and backslashes and must be
    # skipped by length; a picture's hex is not text. A scanner that misses the
    # \bin length would see the "}" inside it as a group end and lose its place.
    body = (
        "{\\pard a{\\*\\atnid X}{\\*\\annotation {\\pard note {\\deleted gone}\\par}}b\\par}"
        "{\\pard {\\pict\\pngblip\\bin3 }}}}\\par}"
        "{\\pard {\\deleted real}\\par}"
    )
    found = oi.inspect(_rtf(body), "rtf")

    assert found.comments == 1
    assert (found.insertions, found.deletions) == (0, 1)  # only "real"; not the comment's

    # The length of \bin is what keeps the scan inside the header: six closing
    # braces of picture data followed by the real end of the picture group.
    inside = "{\\headerr \\pard {\\pict\\bin6 }}}}}}}Text\\par}"
    assert oi.inspect(_rtf(inside), "rtf").headers_footers == 1


def test_rtf_unicode_escape_skips_its_fallback_character():
    # Unicode 32 with fallback "?" is a space. Reading the fallback as text
    # would make an otherwise blank header look like it carries a question
    # mark; and a real character (1090 is a Cyrillic letter) must still count.
    blank = "{\\headerr \\pard \\u32?\\par}"
    letter = "{\\headerr \\pard \\u1090?\\par}"

    assert oi.inspect(_rtf(blank), "rtf").headers_footers == 0
    assert oi.inspect(_rtf(letter), "rtf").headers_footers == 1


# --------------------------------------------------------------------------
# DOC internals (the Word-made DOC files are in the pre-release set)
# --------------------------------------------------------------------------

def _clx(pieces, prcs=()):
    """A Clx for `pieces`: (cp count, raw fc, prm) triples."""
    import struct

    out = b""
    for grpprl in prcs:
        out += b"\x01" + struct.pack("<H", len(grpprl)) + grpprl
    cps, total = [0], 0
    for count, _, _ in pieces:
        total += count
        cps.append(total)
    plc = struct.pack(f"<{len(cps)}I", *cps)
    for _, fc, prm in pieces:
        plc += struct.pack("<HIH", 0, fc, prm)
    return out + b"\x02" + struct.pack("<I", len(plc)) + plc


def test_doc_piece_table_reads_compressed_and_wide_pieces():
    # A real file has both widths: Latin text is stored one byte per character
    # ("compressed"), Cyrillic as UTF-16. Mixing the two up moves every revision
    # range after the first compressed piece, so the characters of a change
    # would be misplaced silently.
    word = bytearray(b"\x00" * 64)
    word[10:15] = b"abc d"                              # compressed: 1 byte per char
    word[30:36] = "xyz".encode("utf-16-le")             # wide: 2 bytes per char
    pieces = oi._Pieces(
        bytes(word),
        _clx([(5, (10 * 2) | 0x40000000, 0), (3, 30, 0)]),
    )

    assert pieces.text(0, 8) == "abc dxyz"
    assert pieces.text(3, 6) == " dx"
    # file bytes 12..14 are chars 2..3 of the first piece; bytes 30..32 are char 5
    assert pieces.cp_ranges(12, 14) == [(2, 4)]
    assert pieces.cp_ranges(30, 32) == [(5, 6)]
    assert pieces.cp_ranges(13, 32) == [(3, 5), (5, 6)]


def test_doc_revision_sprms_are_read_past_other_operands():
    # Property lists mix operand sizes; a reader that miscounts one skips the
    # revision mark behind it. 0xCA57 is a variable-length sprm (length byte
    # first); 0x4804 / 0x4863 carry the author; 0x81 is Word's "on".
    import struct

    def sprm(opcode, operand):
        return struct.pack("<H", opcode) + operand

    other = sprm(0xCA57, b"\x03abc") + sprm(0x6805, b"\x00\x00\x00\x00") + sprm(0x2A33, b"\x01")
    inserted = other + sprm(0x4804, struct.pack("<H", 7)) + sprm(0x0801, b"\x81")
    deleted = sprm(0x4863, struct.pack("<H", 9)) + sprm(0x0800, b"\x01") + other
    plain = other + sprm(0x0800, b"\x00")

    assert oi._revision_sprms(inserted) == (True, False, 7, 0)
    assert oi._revision_sprms(deleted) == (False, True, 0, 9)
    assert oi._revision_sprms(plain) == (False, False, 0, 0)


def test_doc_pieces_can_carry_their_own_revision_properties():
    # A fast-saved file keeps character properties in the Clx and points a piece
    # at them (Prm with the low bit set). Without reading them such a file
    # would show no changes at all.
    import struct

    grpprl = struct.pack("<H", 0x0800) + b"\x01"
    pieces = oi._Pieces(b"\x00" * 64, _clx([(4, 0, 0), (6, 8, (0 << 1) | 1)], prcs=[grpprl]))

    assert pieces.own_properties() == [(4, 10, grpprl)]


def test_doc_story_text_ignores_field_instructions_and_control_characters():
    # What makes a header story "carry text": a printable, non-blank character
    # outside a field's instruction. Word pads every story with paragraph marks
    # (0x0D), cell marks (0x07) and picture placeholders (0x01), and a page
    # number is a field: instruction, separator, result. The empty stories must
    # not count; the page number's result must.
    assert oi._has_visible_text("\r") is False
    assert oi._has_visible_text("\x01\x07\r  \xa0\r") is False
    assert oi._has_visible_text("\x13 PAGE \x14\x15\r") is False   # a field with no result
    assert oi._has_visible_text("\x13 PAGE \x143\x15\r") is True   # result "3"
    assert oi._has_visible_text("\x13 A \x13 B \x14x\x15 \x14\x15") is False  # instruction holds a field
    assert oi._has_visible_text("Верх\r") is True


def test_doc_that_is_not_a_word_file_cannot_be_inspected():
    # A compound file that is not Word's must fail loudly, not report zero
    # changes. A garbage stream is not "a document with nothing in it".
    with pytest.raises(oi.InspectionFailed):
        oi.inspect(b"not a compound file at all", "doc")
    with pytest.raises(oi.InspectionFailed):
        oi.inspect(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600, "doc")


# --------------------------------------------------------------------------
# The command line
# --------------------------------------------------------------------------

def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "trimitdown.cli", *args],
        capture_output=True, text=True, encoding="utf-8", timeout=300,
    )


def test_cli_refuses_with_a_nonzero_exit_and_names_the_remedies(tmp_path):
    revised = tmp_path / "revised.docx"
    revised.write_bytes(_revised_docx())

    result = _cli("convert", str(revised))

    assert result.returncode == 1
    assert "unresolved tracked changes (1 insertion, 1 deletion)" in result.stderr
    assert "--accept-changes" in result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.stderr


def test_cli_accept_changes_prints_text_summary_and_writes_the_report(tmp_path):
    source = tmp_path / "full.docx"
    source.write_bytes(_full_docx())
    report_path = tmp_path / "report.json"

    result = _cli("convert", str(source), "--accept-changes", "--report", str(report_path))

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith(
        "<!-- trimitdown: accepted 1 insertion, 1 deletion; "
        "omitted 2 header/footer parts, 1 comment, 1 image -->"
    )
    # The same counts on stderr as in the line above.
    assert (
        "trimitdown: accepted 1 insertion, 1 deletion; "
        "omitted 2 header/footer parts, 1 comment, 1 image" in result.stderr
    )
    assert json.loads(report_path.read_text(encoding="utf-8")) == {
        "schema": 1,
        "format": "docx",
        "tracked_changes": {"present": True, "insertions": 1, "deletions": 1, "accepted": True},
        "omitted": {"headers_footers": 2, "comments": 1, "images": 1},
    }


def test_cli_report_is_not_written_for_a_refused_document(tmp_path):
    # A report next to a refusal would be read by a pipeline as "converted".
    report_path = tmp_path / "report.json"

    result = _cli("convert", str(_rtf_fixture("legal")), "--report", str(report_path))

    assert result.returncode == 1
    assert not report_path.exists()


def test_cli_report_for_a_pdf_has_the_format_and_the_page_counts(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import pdf_fixtures

    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(pdf_fixtures.ruled_table())
    report_path = tmp_path / "report.json"

    result = _cli("convert", str(pdf), "--report", str(report_path))

    assert result.returncode == 0, result.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["schema"] == 1 and report["format"] == "pdf"
    assert report["pages"] == {
        "total": 1, "accept": 1, "substitute": 0, "scan": 0, "corrupt": 0, "blank": 0,
    }
    assert "tracked_changes" not in report


def test_cli_reports_an_unwritable_report_path(tmp_path):
    result = _cli(
        "convert", str(_rtf_fixture("clean")), "--report", str(tmp_path / "no" / "such" / "dir.json")
    )

    assert result.returncode == 1
    assert "could not write the report" in result.stderr


def test_cli_clean_document_is_silent_on_stderr():
    # No summary line when there is nothing to say: a stderr line on every run
    # is a line nobody reads.
    result = _cli("convert", str(_rtf_fixture("clean")))

    assert result.returncode == 0
    assert result.stderr == ""


# --------------------------------------------------------------------------
# Layering
# --------------------------------------------------------------------------

def test_inspection_module_is_pure_and_lazy():
    # office_inspect is imported by convert.py at the top, so it must cost
    # nothing: no FastAPI (the layering rule), and neither olefile nor anydoc
    # until a DOC or an office file is actually read.
    code = (
        "import sys, trimitdown.convert, trimitdown.office_inspect; "
        "bad = [m for m in ('fastapi', 'olefile', 'anydoc') if m in sys.modules]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    run = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

    assert run.returncode == 0, run.stdout + run.stderr
