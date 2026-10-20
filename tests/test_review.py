"""The review hand-off: the directory an agent reconciles, and the way back.

Tesseract is never needed here. CI runners do not have it, and a skip when it is
missing would break the zero-skips rule, so a fake one is written into tmp_path
and run as [sys.executable, fake.py] -- the same on Windows and Linux, no chmod,
no .bat. Whether the real Tesseract reads our images as the owner's measurement
did is checked outside this repository.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import route_fixtures as rf
from trimitdown import review
from trimitdown.convert import convert_path
from trimitdown.pdf_route import render_markdown
from trimitdown.review import ReviewError, assemble, prepare_review, review_rule

# Bound to plain names: a decorator written "@pytest.mark..." at the start of a
# line reads as an e-mail address to the PII guard on commit.
parametrize = pytest.mark.parametrize
fixture = pytest.fixture

FAKE_TESSERACT = r'''
import json, pathlib, sys
here = pathlib.Path(__file__)
cfg = json.loads(here.with_suffix(".json").read_text(encoding="utf-8"))
with open(here.with_suffix(".log"), "a", encoding="utf-8") as log:
    log.write(json.dumps(sys.argv[1:]) + "\n")
args = sys.argv[1:]
if "--version" in args:
    print("tesseract 5.4.0")
elif "--list-langs" in args:
    print('List of available languages in "fake" (%d):' % len(cfg["langs"]))
    print("\n".join(cfg["langs"]))
elif "--psm" in args and args[args.index("--psm") + 1] == "0":
    print("Page number: 0")
    print("Orientation in degrees: %d" % ((360 - cfg["rotate"]) % 360))
    print("Rotate: %d" % cfg["rotate"])
    print("Orientation confidence: %.2f" % cfg["confidence"])
    print("Script: Cyrillic")
else:
    sys.stdout.buffer.write(cfg["text"].encode("utf-8"))
'''

OCR_TEXT = "распознанный текст страницы\nвторая строка\n"


class Fake:
    def __init__(self, tmp_path, *, langs=("eng", "osd", "rus"), rotate=0, confidence=20.0):
        self.script = tmp_path / "fake_tesseract.py"
        self.script.write_text(FAKE_TESSERACT, encoding="utf-8")
        self.script.with_suffix(".json").write_text(json.dumps(
            {"langs": list(langs), "rotate": rotate, "confidence": confidence, "text": OCR_TEXT}
        ), encoding="utf-8")
        self.cmd = [sys.executable, str(self.script)]

    def calls(self) -> list[list[str]]:
        log = self.script.with_suffix(".log")
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    def ocr_images(self) -> list[str]:
        return [Path(c[0]).name for c in self.calls()
                if c and not c[0].startswith("--") and c[c.index("--psm") + 1] != "0"]


def _pdf(tmp_path, data=None, name="doc.pdf"):
    pdf = tmp_path / name
    pdf.write_bytes(data if data is not None else rf.mixed_route_document())
    return pdf


def _manifest(out):
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def _pages(manifest):
    return {p["page"]: p for p in manifest["pages"]}


# --- what goes into the directory ---------------------------------------------------

def test_scan_without_a_layer_gets_a_tesseract_candidate(tmp_path):
    fake = Fake(tmp_path)
    out = tmp_path / "review"

    manifest = prepare_review(_pdf(tmp_path), out, tesseract=fake.cmd)
    page = _pages(manifest)[3]

    assert manifest["ocr"]["status"] == "ok"
    assert manifest["ocr"]["version"] == "5.4.0"
    assert page["path"] == "scan" and page["review"] is True
    assert page["candidate_source"] == "tesseract"
    assert (out / page["candidate_text"]).read_text(encoding="utf-8") == OCR_TEXT
    assert (out / page["image"]).is_file()
    # The measured configuration, not the Tesseract default.
    ocr_call = next(c for c in fake.calls()
                    if c[0].endswith("p0003.png") and c[c.index("--psm") + 1] != "0")
    assert ocr_call[ocr_call.index("-l") + 1] == "rus"
    assert ocr_call[ocr_call.index("--psm") + 1] == "3"


def test_scan_with_an_ocr_layer_is_reviewed_against_that_layer(tmp_path):
    """Owner's decision B1: the existing OCR layer is the candidate; Tesseract
    runs only where there is nothing to start from.

    Fails if every scan page is OCR'd afresh (verified: page 4's image appeared
    in the fake's call log).
    """
    fake = Fake(tmp_path)
    out = tmp_path / "review"

    page = _pages(prepare_review(_pdf(tmp_path), out, tesseract=fake.cmd))[4]

    assert page["candidate_source"] == "ocr_layer"
    assert page["ocr"] == {"status": "not_needed"}
    assert "p0004.png" not in fake.ocr_images()
    candidate = (out / page["candidate_text"]).read_text(encoding="utf-8")
    assert sum(1 for ch in candidate if "Ѐ" <= ch <= "ӿ") > 500


def test_ocr_fresh_runs_tesseract_on_the_layer_page_and_keeps_the_layer(tmp_path):
    fake = Fake(tmp_path)
    out = tmp_path / "review"

    page = _pages(prepare_review(_pdf(tmp_path), out, tesseract=fake.cmd, ocr_fresh=True))[4]

    assert page["candidate_source"] == "tesseract"
    assert "p0004.png" in fake.ocr_images()
    assert (out / page["layer_text"]).read_text(encoding="utf-8").strip()


def test_without_tesseract_pages_still_go_to_review(tmp_path):
    """No Tesseract: the candidate is empty and the page is still sent.

    Fails if pages without a candidate are filtered out of the review (verified),
    which would turn a missing tool into silently missing pages.
    """
    out = tmp_path / "review"

    manifest = prepare_review(_pdf(tmp_path), out, tesseract=str(tmp_path / "no-such-tesseract"))
    pages = _pages(manifest)

    assert manifest["ocr"]["status"] == "unavailable"
    assert manifest["summary"]["review_pages"] == [3, 4, 5]
    assert manifest["summary"]["without_candidate"] == [3, 5]
    for number in (3, 5):
        assert pages[number]["review"] is True
        assert pages[number]["ocr"]["status"] == "unavailable"
        assert (out / pages[number]["candidate_text"]).read_text(encoding="utf-8") == ""
        assert (out / pages[number]["image"]).is_file()


def test_a_missing_language_is_reported_not_replaced_with_english(tmp_path):
    """Without rus, Cyrillic OCRs to confident garbage: no OCR at all is better.

    Fails if recognition falls back to another installed language (verified:
    the fake was called with -l eng).
    """
    fake = Fake(tmp_path, langs=("eng", "osd"))
    out = tmp_path / "review"

    manifest = prepare_review(_pdf(tmp_path), out, tesseract=fake.cmd)

    assert manifest["ocr"]["status"] == "lang_missing"
    assert manifest["ocr"]["missing"] == ["rus"]
    assert fake.ocr_images() == []
    assert _pages(manifest)[3]["ocr"]["status"] == "lang_missing"


def test_no_ocr_flag_sends_pages_without_a_candidate(tmp_path):
    fake = Fake(tmp_path)
    manifest = prepare_review(_pdf(tmp_path), tmp_path / "review", tesseract=fake.cmd, ocr=False)

    assert manifest["ocr"]["status"] == "disabled"
    assert fake.calls() == []
    assert manifest["summary"]["without_candidate"] == [3, 5]


def test_a_full_page_scan_hands_over_the_source_image(tmp_path):
    # The owner's rule: the source image when it is the whole page.
    fake = Fake(tmp_path)
    out = tmp_path / "review"
    page = _pages(prepare_review(_pdf(tmp_path, rf.one(rf.scanned_image_page())), out,
                                 tesseract=fake.cmd))[1]

    from PIL import Image

    assert page["image_kind"] == "source"
    with Image.open(out / page["image"]) as image:
        assert image.size == rf.IMAGE_SIZE


def test_a_rotated_scan_is_rendered_not_extracted(tmp_path):
    """/Rotate 90: the source image lies on its side, so the page is rendered.

    Fails if the source image is taken whenever it fills the page (verified:
    image_kind became "source" and the agent would compare against a sideways
    picture).
    """
    fake = Fake(tmp_path)
    out = tmp_path / "review"
    page = _pages(prepare_review(_pdf(tmp_path, rf.build([rf.scanned_image_page(rotate=90)])),
                                 out, tesseract=fake.cmd))[1]

    from PIL import Image

    assert page["image_kind"] == "render300"
    with Image.open(out / page["image"]) as image:
        assert image.width > image.height  # rendered as displayed: landscape


def test_confident_orientation_rotates_the_saved_image(tmp_path):
    # Saved rotated, so the reviewer looks at the picture OCR read.
    fake = Fake(tmp_path, rotate=90, confidence=25.0)
    out = tmp_path / "review"
    page = _pages(prepare_review(_pdf(tmp_path, rf.one(rf.scanned_image_page())), out,
                                 tesseract=fake.cmd))[1]

    from PIL import Image

    assert page["rotation_applied"] == 90
    assert page["ocr"]["orientation"] == "checked"
    with Image.open(out / page["image"]) as image:
        assert image.size == (rf.IMAGE_SIZE[1], rf.IMAGE_SIZE[0])


def test_low_confidence_orientation_is_left_for_the_eye(tmp_path):
    """Owner's rule: under confidence 10, do not rotate -- look.

    Fails if the threshold is ignored (verified: the image was rotated).
    """
    fake = Fake(tmp_path, rotate=90, confidence=4.8)
    out = tmp_path / "review"
    page = _pages(prepare_review(_pdf(tmp_path, rf.one(rf.scanned_image_page())), out,
                                 tesseract=fake.cmd))[1]

    assert page["rotation_applied"] == 0
    assert page["ocr"]["orientation"] == "low_confidence"


def test_manifest_lists_every_page_from_1_with_its_path(tmp_path):
    manifest = prepare_review(_pdf(tmp_path), tmp_path / "review", ocr=False)

    assert manifest["pdf"]["page_count"] == 7
    assert [(p["page"], p["path"]) for p in manifest["pages"]] == sorted(rf.MIXED_EXPECTED.items())
    pages = _pages(manifest)
    # Blank and substitute pages are recorded, not sent.
    assert pages[6]["review"] is False and "image" not in pages[6]
    assert pages[2]["review"] is False
    assert manifest["summary"]["estimated_cost_usd"] == 0.12
    # The owner's session proposed these metric names; they are kept.
    for key in ("chars", "letters", "cyr_ratio", "latin_in_cyr_words", "mixed_script_words",
                "scripts", "pi_letters", "ref_letters", "gate_fired", "image_coverage"):
        assert key in pages[1]["metrics"]


def test_review_substitute_sends_those_pages_with_their_text_as_candidate(tmp_path):
    out = tmp_path / "review"
    manifest = prepare_review(_pdf(tmp_path), out, ocr=False, include_substitute=True)
    page = _pages(manifest)[2]

    assert page["review"] is True
    assert page["candidate_source"] == "pypdf"
    assert (out / page["candidate_text"]).read_text(encoding="utf-8").strip()
    assert manifest["summary"]["review_pages"] == [2, 3, 4, 5, 7]


def test_text_under_an_image_is_recorded_in_the_manifest(tmp_path):
    """Owner's decision B1: accepted, and its image coverage written down.

    Fails if accepted pages drop out of the manifest or the coverage is not
    measured (verified by computing coverage only for review pages).
    """
    manifest = prepare_review(_pdf(tmp_path, rf.one(rf.image_over_text_page())),
                              tmp_path / "review", ocr=False)
    page = _pages(manifest)[1]

    assert page["path"] == "accept" and page["review"] is False
    # 468 x 300 pt of a 612 x 792 page: about 29 %, on a 50x50 grid.
    assert 0.25 <= page["metrics"]["image_coverage"] <= 0.35


def test_review_md_is_the_packaged_rule_with_the_chosen_marks(tmp_path):
    out_ru = tmp_path / "ru"
    out_en = tmp_path / "en"
    prepare_review(_pdf(tmp_path), out_ru, ocr=False)
    prepare_review(_pdf(tmp_path), out_en, ocr=False, markers="en")

    ru = (out_ru / "REVIEW.md").read_text(encoding="utf-8")
    en = (out_en / "REVIEW.md").read_text(encoding="utf-8")
    assert ru == review_rule("ru")
    assert en == review_rule("en")
    assert "=== стр. N ===" in ru and "[неразборчиво]" in ru and "[печать]" in ru
    assert "=== page N ===" in en and "[illegible]" in en
    assert "{{" not in ru and "{{" not in en, "a placeholder was left unfilled"
    assert _manifest(out_ru)["markers"] == "ru"


def test_review_rule_ships_in_the_package():
    # The rule is package data. Without the pyproject line the wheel loses it and
    # every review directory is written without its procedure.
    from importlib import resources

    try:
        import tomllib
    except ModuleNotFoundError:  # 3.10
        import tomli as tomllib

    assert (resources.files("trimitdown") / "review_rule.md").is_file()
    project = tomllib.loads((Path(__file__).resolve().parent.parent / "pyproject.toml")
                            .read_text(encoding="utf-8"))
    assert "review_rule.md" in project["tool"]["setuptools"]["package-data"]["trimitdown"]


def test_a_directory_with_files_in_it_is_refused(tmp_path):
    """A second run must not overwrite a reviewer's work."""
    out = tmp_path / "review"
    (out / "reviewed").mkdir(parents=True)
    (out / "reviewed" / "doc.txt").write_text("work", encoding="utf-8")

    with pytest.raises(ReviewError, match="not empty"):
        prepare_review(_pdf(tmp_path), out, ocr=False)
    assert (out / "reviewed" / "doc.txt").read_text(encoding="utf-8") == "work"


def test_two_runs_write_identical_directories(tmp_path):
    # No timestamps, no absolute paths: a rerun reproduces the directory.
    pdf = _pdf(tmp_path)
    prepare_review(pdf, tmp_path / "a", ocr=False)
    prepare_review(pdf, tmp_path / "b", ocr=False)
    for name in ("manifest.json", "document.md"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()


# --- the way back ----------------------------------------------------------------------

@fixture
def prepared(tmp_path):
    pdf = _pdf(tmp_path)
    out = tmp_path / "review"
    prepare_review(pdf, out, ocr=False)
    return pdf, out


def test_assemble_takes_the_owners_doc_txt_format(prepared):
    """Owner's decision B4: doc.txt with "=== стр. N ===" is the main format.

    Fails if assemble only reads per-page files (verified).
    """
    pdf, out = prepared
    (out / "reviewed" / "doc.txt").write_text(
        "=== стр. 3 ===\nстраница три\n\n=== стр. 4 ===\nстраница четыре\n"
        "=== стр. 5 ===\nстраница пять\n", encoding="utf-8")

    text = assemble(out, page_anchors=False)

    routes = convert_path(pdf).pages
    expected = [r.text for r in routes]
    expected[2], expected[3], expected[4] = "страница три\n", "страница четыре\n", "страница пять\n"
    assert text == "\n\n".join(expected)
    assert "has no usable text layer" not in text


def test_assemble_takes_per_page_files_and_english_headers(prepared):
    _, out = prepared
    (out / "reviewed" / "p0003.txt").write_text("three\n", encoding="utf-8")
    (out / "reviewed" / "doc.txt").write_text("=== page 4 ===\nfour\n=== page 5 ===\nfive\n",
                                              encoding="utf-8")
    text = assemble(out)
    assert "three\n" in text and "four\n" in text and "five\n" in text


def test_assemble_refuses_a_page_reviewed_twice(prepared):
    _, out = prepared
    (out / "reviewed" / "p0003.txt").write_text("three\n", encoding="utf-8")
    (out / "reviewed" / "doc.txt").write_text("=== стр. 3 ===\nтри\n", encoding="utf-8")
    with pytest.raises(ReviewError, match="page 3 is reviewed twice"):
        assemble(out, allow_missing=True)


def test_assemble_refuses_a_page_the_pdf_does_not_have(prepared):
    """Fails if reviewed text for an unknown page is ignored rather than refused."""
    _, out = prepared
    (out / "reviewed" / "doc.txt").write_text("=== стр. 12 ===\nчужое\n", encoding="utf-8")
    with pytest.raises(ReviewError, match=r"\[12\]"):
        assemble(out, allow_missing=True)


def test_assemble_refuses_text_for_a_page_not_sent_for_review(prepared):
    _, out = prepared
    (out / "reviewed" / "p0001.txt").write_text("переписано\n", encoding="utf-8")
    with pytest.raises(ReviewError, match="not sent for review"):
        assemble(out, allow_missing=True)


def test_assemble_stops_on_unreviewed_pages_unless_allowed(prepared):
    pdf, out = prepared
    (out / "reviewed" / "p0003.txt").write_text("three\n", encoding="utf-8")

    with pytest.raises(ReviewError, match=r"\[4, 5\]"):
        assemble(out)

    partial = assemble(out, allow_missing=True)
    assert "three\n" in partial
    assert "[trimitdown: page 5 has no usable text layer (corrupt)]" in partial


def test_an_unreviewed_directory_assembles_to_the_conversion(prepared):
    # The review directory adds nothing but the reviewed pages: with nothing
    # reviewed it gives back exactly what convert gives, with the same anchors.
    pdf, out = prepared
    routes = list(convert_path(pdf).pages)
    assert assemble(out, allow_missing=True, page_anchors=False) == convert_path(pdf).text
    assert assemble(out, allow_missing=True) == render_markdown(routes, page_anchors=True)


def test_assemble_keeps_the_page_anchors_by_default(prepared):
    """A reviewed scan is cited by page; 0.2.0 dropped every anchor here.

    Fails if assemble goes back to joining bare pages (verified), and if a
    reviewed page loses its own anchor rather than following it.
    """
    pdf, out = prepared
    (out / "reviewed" / "doc.txt").write_text(
        "=== стр. 3 ===\nтри\n=== стр. 4 ===\nчетыре\n=== стр. 5 ===\nпять\n", encoding="utf-8")

    text = assemble(out)

    pages = [r.page for r in convert_path(pdf).pages]
    assert [int(n) for n in re.findall(r"^<!-- page (\d+) -->$", text, re.M)] == pages
    assert "<!-- page 3 -->\nтри\n" in text and "<!-- page 5 -->\nпять\n" in text
    assert "<!-- page" not in assemble(out, page_anchors=False)


def test_document_md_and_anchored_conversion_are_one_format(prepared):
    # One function builds both, so a review directory's document.md is what
    # convert --page-anchors prints. Fails if the two formats drift apart.
    pdf, out = prepared
    routes = list(convert_path(pdf).pages)
    assert (out / "document.md").read_text(encoding="utf-8") == render_markdown(routes, page_anchors=True)


def test_assemble_ignores_a_blank_page_that_was_not_sent(prepared):
    """The owner's procedure writes every page, a blank one as its header alone.

    0.2.0 refused that page as "not sent for review", so a reviewer who followed
    the rule could not assemble at all. A header with no text is dropped; text
    for a page that was not sent is still refused (the test above). Fails if
    the empty page is refused again (verified).
    """
    pdf, out = prepared
    not_sent = [r.page for r in convert_path(pdf).pages if not r.needs_review]
    blank_header = "".join(f"=== стр. {n} ===\n\n" for n in not_sent)
    (out / "reviewed" / "doc.txt").write_text(
        blank_header + "=== стр. 3 ===\nтри\n=== стр. 4 ===\nчетыре\n=== стр. 5 ===\nпять\n",
        encoding="utf-8")

    text = assemble(out, page_anchors=False)

    assert "три\n" in text and "пять\n" in text
    plain = convert_path(pdf).pages
    for r in plain:
        if not r.needs_review and r.text:
            assert r.text in text


def test_assemble_notices_an_edited_document(prepared):
    _, out = prepared
    document = out / "document.md"
    document.write_text(document.read_text(encoding="utf-8").replace("<!-- page 6 -->\n", ""),
                        encoding="utf-8")
    with pytest.raises(ReviewError, match="edited"):
        assemble(out, allow_missing=True)


# --- Tesseract discovery ------------------------------------------------------------------

def test_find_tesseract_order(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract-explicit"
    exe.write_text("", encoding="utf-8")
    env = tmp_path / "tesseract-env"
    env.write_text("", encoding="utf-8")
    known = tmp_path / "Tesseract-OCR" / "tesseract.exe"
    known.parent.mkdir()
    known.write_text("", encoding="utf-8")

    monkeypatch.setenv("TRIMITDOWN_TESSERACT", str(env))
    monkeypatch.setattr(review.shutil, "which", lambda name: "/on/path/tesseract")
    monkeypatch.setattr(review, "_known_locations", lambda: [known])

    assert review.find_tesseract(str(exe)) == [str(exe)]
    assert review.find_tesseract() == [str(env)]
    monkeypatch.delenv("TRIMITDOWN_TESSERACT")
    assert review.find_tesseract() == ["/on/path/tesseract"]
    # "command not found" is not "not installed": the installer's own location
    # is checked when PATH has nothing. Fails if that fallback is dropped.
    monkeypatch.setattr(review.shutil, "which", lambda name: None)
    assert review.find_tesseract() == [str(known)]
    monkeypatch.setattr(review, "_known_locations", lambda: [])
    assert review.find_tesseract() is None
    # An explicit path that is not there is not silently replaced by another.
    assert review.find_tesseract(str(tmp_path / "missing")) is None


# --- images on demand -----------------------------------------------------------------------

def test_render_writes_the_requested_pages(tmp_path):
    pdf = _pdf(tmp_path)
    written = review.render_pages(pdf, "1,3-4", tmp_path / "img")
    assert [p.stem for p in written] == ["p0001", "p0003", "p0004"]
    assert all(p.is_file() for p in written)


@parametrize("spec", ["0", "8", "3-2", "a", ""])
def test_render_refuses_pages_outside_the_document(spec):
    with pytest.raises(ValueError):
        review.parse_pages(spec, 7)


# --- the layering invariant ---------------------------------------------------------------

def test_review_does_not_import_fastapi(tmp_path):
    # Same boundary as trimitdown.convert: the CLI package has no web stack, so
    # a lazy FastAPI import in the review path would crash the installed CLI.
    # Calls the code, not just the import, for the reason given in
    # test_convert_pure.py::test_convert_path_does_not_import_fastapi.
    pdf = _pdf(tmp_path)
    code = (
        "import sys; from trimitdown.review import prepare_review, assemble; "
        f"prepare_review(r'{pdf}', r'{tmp_path / 'r'}', ocr=False); "
        f"assemble(r'{tmp_path / 'r'}', allow_missing=True); "
        "sys.exit(1 if 'fastapi' in sys.modules else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


def test_convert_does_not_import_the_review_module():
    # convert is "a path in, text out"; the module that writes directories and
    # starts processes stays out of it.
    code = "import sys, trimitdown.convert; sys.exit(1 if 'trimitdown.review' in sys.modules else 0)"
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
