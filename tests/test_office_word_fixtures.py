"""The Word-made DOCX, DOC and ODT behind the 0.3.1 office layer. Pre-release gate.

These are the documents the counts in office_inspect were checked against: made
in Word 365 from synthetic text, with the author scrubbed, and measured in
Word's own object model (Revisions, Comments, InlineShapes, ListString):

    file            revisions        comments  header+footer  images
    legal.*         1 ins + 1 del    1         1 + 1          1
    legal.odt       accepted on save 1         1 + 1          1
    revonly.*       1 ins + 1 del    0         0              0
    clean.*         0                0         0              0
    num.*           0                0         0              0

They are not in this tree. The pre-commit guard rejects new binary documents
(it cannot scan them) and reads their text for the word "contract", so the files
live in the owner's private directory and the tests carry the `corpus` marker:
`pytest -m "not corpus"` (CI) leaves them out and its zero-skips rule holds,
`pytest -m corpus` runs them where the directory exists. Point
TRIMITDOWN_OFFICE_FIXTURES at it, or at <private>/office-0.4/fixtures
(TRIMITDOWN_PRIVATE, see conftest.py).

What CI keeps of this evidence: the four RTF files in tests/data/office, and
DOCX/RTF built from raw text in test_office_changes.py.
"""
import os
import re
from pathlib import Path

import pytest

from conftest import PRIVATE_DIR
from trimitdown import office_inspect as oi
from trimitdown.convert import ConversionError, convert_path

pytestmark = pytest.mark.corpus

FORMATS = ("docx", "doc", "rtf")
DELETED = "Этаудаление"
INSERTED = "Тетавставка"


def _directory() -> Path:
    raw = os.environ.get("TRIMITDOWN_OFFICE_FIXTURES")
    return Path(raw) if raw else PRIVATE_DIR / "office-0.4" / "fixtures"


def _fixture(name: str) -> Path:
    path = _directory() / name
    if not path.is_file():
        pytest.skip(f"{path} is not there; set TRIMITDOWN_OFFICE_FIXTURES")
    return path


def test_unresolved_changes_are_refused_in_every_format_with_the_counts():
    for name in ("legal", "revonly"):
        for fmt in FORMATS:
            with pytest.raises(ConversionError) as caught:
                convert_path(_fixture(f"{name}.{fmt}"))
            assert "unresolved tracked changes (1 insertion, 1 deletion)" in str(caught.value), (name, fmt)


def test_clean_documents_convert_without_a_note_in_every_format():
    for fmt in FORMATS:
        result = convert_path(_fixture(f"clean.{fmt}"))
        assert not result.text.startswith("<!--"), fmt
        assert result.report["omitted"] == {"headers_footers": 0, "comments": 0, "images": 0}, fmt


def test_revonly_docx_accepted_equals_clean_docx_apart_from_the_note():
    # clean.docx is the same document with the changes accepted in Word. Equal
    # to the character means anydoc's DOCX reading IS Word's "accept all".
    accepted = convert_path(_fixture("revonly.docx"), accept_changes=True)
    clean = convert_path(_fixture("clean.docx"))

    assert INSERTED in accepted.text and DELETED not in accepted.text
    note, _, rest = accepted.text.partition("\n\n")
    assert note == "<!-- trimitdown: accepted 1 insertion, 1 deletion -->"
    assert rest == clean.text


def test_accept_changes_still_refuses_doc_and_rtf():
    for name in ("legal", "revonly"):
        for fmt in ("doc", "rtf"):
            with pytest.raises(ConversionError, match="cannot repair that for this format"):
                convert_path(_fixture(f"{name}.{fmt}"), accept_changes=True)


def test_legal_docx_accepted_carries_wordss_numbers():
    result = convert_path(_fixture("legal.docx"), accept_changes=True)

    assert result.text.split("\n", 1)[0] == (
        "<!-- trimitdown: accepted 1 insertion, 1 deletion; "
        "omitted 2 header/footer parts, 1 comment, 1 image -->"
    )
    assert result.report["omitted"] == {"headers_footers": 2, "comments": 1, "images": 1}
    for word in ("Мюкомментарий", "Нюверхний", "Ксиnижний", DELETED):
        assert word not in result.text, word
    assert "Каппасноска" in result.text  # footnotes are carried


def test_doc_counts_are_wordss_on_the_word_made_files():
    # The DOC reader is the one written from the specification rather than from
    # a library, so it gets its own direct check against Word's numbers.
    expected = {
        "legal": (1, 1, 2, 1),
        "revonly": (1, 1, 0, 0),
        "clean": (0, 0, 0, 0),
        "num": (0, 0, 0, 0),
    }
    for name, (ins, dele, headers, comments) in expected.items():
        found = oi.inspect(_fixture(f"{name}.doc").read_bytes(), "doc")
        assert (found.insertions, found.deletions, found.headers_footers, found.comments) == (
            ins, dele, headers, comments,
        ), name


def test_doc_omissions_through_the_whole_conversion(tmp_path):
    # legal.doc with the revision flags switched off in the character properties
    # (Word writes the operand 0x81, "on"; 0 is "off"), so that a DOC carrying a
    # comment, headers, footers and an image but no changes can be converted.
    import olefile

    target = tmp_path / "legal-flat.doc"
    target.write_bytes(_fixture("legal.doc").read_bytes())
    ole = olefile.OleFileIO(str(target), write_mode=True)
    try:
        word = bytearray(ole.openstream("WordDocument").read())
        # Two property lists carry it: the deleted run's, and the one shared by
        # the inserted text and its paragraph mark.
        flagged = [m.start() for m in re.finditer(rb"[\x00\x01]\x08\x81", bytes(word))]
        assert len(flagged) == 2
        for offset in flagged:
            word[offset + 2] = 0
        ole.write_stream("WordDocument", bytes(word))
    finally:
        ole.close()

    result = convert_path(target)

    assert result.report["omitted"] == {"headers_footers": 2, "comments": 1, "images": 1}
    assert result.report["tracked_changes"]["present"] is False
    assert result.text.startswith(
        "<!-- trimitdown: omitted 2 header/footer parts, 1 comment, 1 image -->\n\n"
    )


def test_no_omission_line_on_clean_and_numbered_documents():
    for name in ("clean", "num"):
        for fmt in FORMATS:
            assert "trimitdown:" not in convert_path(_fixture(f"{name}.{fmt}")).text, (name, fmt)


def test_odt_is_refused():
    # Saved from Word as ODT: second-level numbering does not restart ("2.1."
    # became "2.3.") and a comment is pasted into a word. Both files, so that
    # the refusal does not depend on the document having a comment.
    for name in ("legal", "num"):
        with pytest.raises(ConversionError, match="ODT is not converted"):
            convert_path(_fixture(f"{name}.odt"))


def test_odt_is_recognised_by_content_and_a_docx_named_odt_is_not_refused(tmp_path):
    renamed = tmp_path / "report.docx"
    renamed.write_bytes(_fixture("num.odt").read_bytes())
    with pytest.raises(ConversionError, match="ODT is not converted"):
        convert_path(renamed)

    docx_named_odt = tmp_path / "report.odt"
    docx_named_odt.write_bytes(_fixture("clean.docx").read_bytes())
    assert "Омегазаголовок" in convert_path(docx_named_odt).text


def test_word_numbering_is_exactly_wordss_in_every_format():
    # The three readers agree with each other and with what Word showed.
    outputs = {fmt: convert_path(_fixture(f"num.{fmt}")).text for fmt in FORMATS}

    for fmt, text in outputs.items():
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
            assert line in text, (fmt, line)
    assert outputs["docx"] == outputs["doc"] == outputs["rtf"]


def test_footnotes_and_vertical_merges_survive_in_every_format():
    for fmt in FORMATS:
        text = convert_path(_fixture(f"clean.{fmt}")).text
        assert "Йотаосновной[^1]" in text, fmt
        assert "[^1]: Каппасноска текст сноски" in text, fmt
        assert "|  | Передать документы Пиячейка | 5 дней |" in text, fmt
