"""The PDF route: which path each page takes, and what it puts in the document.

Every test here was checked against a deliberately broken route (the breakage
is named in each comment) and went red; a test that stays green on the broken
code is worse than none.
"""
import io
import unicodedata

import pdf_inspector
import pytest

import route_fixtures as rf
from trimitdown import pdf_route
from trimitdown.convert import ConversionError, convert_path
from trimitdown.pdf_route import decide, render_markdown, route_pdf


def _cyrillic(text: str) -> int:
    return sum(1 for ch in text if "CYRILLIC" in unicodedata.name(ch, ""))


def _route(tmp_path, data: bytes, name: str = "doc.pdf"):
    pdf = tmp_path / name
    pdf.write_bytes(data)
    return route_pdf(pdf)


# --- the whole table on one document ----------------------------------------------

def test_every_path_on_one_document(tmp_path):
    """One page per path, numbered from 1, in a known order.

    The single test that would notice two rules swapping order; each rule also
    has its own test below.
    """
    routes = _route(tmp_path, rf.mixed_route_document())

    assert {r.page: r.path for r in routes} == rf.MIXED_EXPECTED


# --- one test per rule -------------------------------------------------------------

def test_frames_page_is_substituted_with_its_text(tmp_path):
    """Rule 4: pdf-inspector empty, layer intact, reference sane -> substitute.

    The 87-page class: pdf-inspector flags the box-drawing frames as garbled and
    returns nothing. Fails if rule 4 is switched off (verified: the page then
    went to corrupt and the document lost 418 letters).
    """
    routes = _route(tmp_path, rf.one(rf.box_drawing_form_page()))

    assert [r.path for r in routes] == ["substitute"]
    assert routes[0].source == "pypdf"
    text = render_markdown(routes)
    assert _cyrillic(text) >= 300
    # The frames themselves are dropped: tokens, no information.
    assert not any(0x2500 <= ord(ch) <= 0x257F for ch in text)


def test_silent_alphabet_swap_is_caught_by_the_gate(tmp_path):
    """Rule 6: pdf-inspector returns text with no flag, in the wrong alphabet.

    needs_ocr is False here, as it was on the 12 measured silent pages. Fails if
    the gate is not run on pages pdf-inspector returned text for (verified by
    replacing the gate_fires call with "did not fire": the page was accepted
    in Latin).
    """
    routes = _route(tmp_path, rf.one(rf.actualtext_latin_over_cyrillic_page()))

    assert routes[0].metrics["needs_ocr"] is False
    assert routes[0].path == "substitute"
    assert "gate_fired" in routes[0].flags
    assert _cyrillic(routes[0].text) > 500


def test_invisible_ocr_layer_is_a_scan_with_its_layer_kept(tmp_path):
    """Rule 3: an OCR layer under a page image is a scan (owner's decision B1).

    pdf-inspector says invisible_text_layer, not scanned. Fails if SCAN_REASONS
    is narrowed to {"scanned"} (verified: the page became substitute and its
    unverified OCR text went out as if it were a text layer).
    """
    routes = _route(tmp_path, rf.one(rf.invisible_ocr_layer_page()))

    assert routes[0].path == "scan"
    assert routes[0].source == "ocr_layer"
    # Plain convert keeps the layer text, with a one-line note that it is
    # unverified -- otherwise 0.2 would drop text the previous engine returned.
    assert routes[0].text.startswith("[trimitdown: page 1: OCR layer, not verified]\n")
    assert _cyrillic(routes[0].text) > 500


def test_image_only_page_is_a_scan_marked_with_its_page_number_from_1(tmp_path):
    """Rule 2 and page numbering: the marker names the page as a person counts.

    The scan sits on the second page. Fails if the 0-based PageMarkdown.page is
    used without +1 (verified: the marker said page 1).
    """
    routes = _route(tmp_path, rf.build([rf.cyrillic_prose_page(), rf.scanned_image_page()]))

    assert [r.path for r in routes] == ["accept", "scan"]
    assert routes[1].page == 2
    assert routes[1].text == "[trimitdown: page 2 has no usable text layer (scan)]\n"


def test_vector_graphics_without_text_are_a_scan_not_blank(tmp_path):
    # No layer, but something is drawn: the owner's rule says look at the image,
    # zero characters does not mean an empty page. Fails if blank were decided
    # by the layer alone.
    routes = _route(tmp_path, rf.one(rf.vector_only_page()))
    assert routes[0].path == "scan"


def test_blank_sheet_is_blank_and_contributes_nothing(tmp_path):
    """Rule 1: no layer and no ink -> blank, not a paid review.

    Fails if rule 1 is removed (verified: the sheet went to scan).
    """
    routes = _route(tmp_path, rf.one(rf.blank_page()))

    assert routes[0].path == "blank"
    assert routes[0].text == ""
    assert not routes[0].needs_review


def test_garbage_at_every_decoder_is_corrupt(tmp_path):
    """Rule 5: cp1251 through a font with no ToUnicode reads as Latin-1 soup everywhere.

    Fails if is_sane always says yes (verified: the soup was substituted into
    the document as text).
    """
    routes = _route(tmp_path, rf.one(rf.cp1251_mojibake_page()))

    assert routes[0].path == "corrupt"
    assert routes[0].metrics["ref_sane"] == "latin1_mojibake"
    assert routes[0].text == "[trimitdown: page 1 has no usable text layer (corrupt)]\n"
    assert routes[0].needs_review


def test_numeric_table_is_accepted_not_corrupt(tmp_path):
    # A page of sums is mostly digits. Fails if digits count against the
    # letter share (the page then went to corrupt and to paid review).
    routes = _route(tmp_path, rf.one(rf.numeric_table_page()))
    assert routes[0].path == "accept"


def test_image_over_text_is_accepted_on_purpose(tmp_path):
    """Owner's decision B1: text under an image is accepted in 0.2.0.

    It is the same shape as an OCR layer under a scan, and it may be text an
    overlay was meant to hide; that is recorded (image_coverage in the review
    manifest, test_review.py), not routed. This test pins the decision so that
    changing it is a decision too.
    """
    routes = _route(tmp_path, rf.one(rf.image_over_text_page()))

    assert routes[0].path == "accept"
    assert routes[0].metrics["needs_ocr"] is False


def test_accept_pages_are_pdf_inspector_byte_for_byte(tmp_path):
    """The benchmark is comparable only if accepted pages are untouched.

    Fails if anything is added to accepted pages -- a separator, a page marker,
    trailing whitespace handling (verified by appending a page comment).
    """
    data = rf.build([rf.cyrillic_prose_page(1), rf.latin_prose_page(), rf.cyrillic_prose_page(9)])
    routes = _route(tmp_path, data)
    pure = pdf_inspector.extract_pages_markdown_bytes(data)

    assert [r.path for r in routes] == ["accept"] * 3
    assert render_markdown(routes) == "\n\n".join(p.markdown for p in pure.pages)


def test_reason_identifiers_are_the_ones_the_route_keys_on():
    """The route keys on strings pdf-inspector does not document.

    If upstream renames a reason, raising the pin turns this red instead of the
    route silently ceasing to recognise scans.
    """
    frames = pdf_inspector.extract_pages_markdown_bytes(rf.one(rf.box_drawing_form_page()))
    layer = pdf_inspector.extract_pages_markdown_bytes(rf.one(rf.invisible_ocr_layer_page()))

    assert frames.ocr_reasons_by_page[0].reasons == ["suspected_garbled_text"]
    assert layer.ocr_reasons_by_page[0].reasons == ["invisible_text_layer"]
    assert "invisible_text_layer" in pdf_route.SCAN_REASONS
    assert "scanned" in pdf_route.SCAN_REASONS


# --- rules that need inputs no synthetic PDF produces ------------------------------

def _sane_cyrillic(words: int = 40) -> str:
    return " ".join(rf.cyrillic_lines(words // 8 + 1, 8, seed=11))


def test_an_emptied_short_page_is_substituted_below_the_gate_floor():
    """Rule 4 is not subject to the gate's 20-letter floor.

    1.25.2 empties short pages entirely; a page with six letters in its layer
    is still a lost page. Fails if rule 4 is made to require the gate's
    thresholds (verified: the page was accepted empty).
    """
    path, _, _ = decide(pi_markdown="", reasons=set(), reference="стр два",
                        layer_chars=7, blank=False)
    assert path == "substitute"


def test_vector_text_reason_with_an_intact_layer_is_substituted():
    # Measured on public FNS forms: pdf-inspector gives "vector_text" and an
    # empty page while the layer holds the form's text. Not a scan reason.
    path, _, _ = decide(pi_markdown="", reasons={"vector_text"}, reference=_sane_cyrillic(),
                        layer_chars=300, blank=False)
    assert path == "substitute"


def test_gate_fired_with_garbage_on_both_sides_goes_to_review():
    """The lead's correction to rule 7: garbage on both sides is corrupt.

    The design table accepted a page whenever the gate fired and the reference
    was garbage. If pdf-inspector's text is garbage as well, that let garbage
    through silently. Fails if rule 7 is restored as written (verified).
    """
    soup = ("налог сбор плательщик ведомость " * 10).encode("cp1251").decode("latin-1")
    path, flags, _ = decide(pi_markdown="#$&@^~ " * 30, reasons=set(), reference=soup,
                            layer_chars=400, blank=False)
    assert path == "corrupt"
    assert "gate_fired" in flags


def test_gate_fired_with_a_sane_candidate_and_garbage_reference_is_accepted():
    # The other half of rule 7: pdf-inspector's text is fine, the reference is
    # the one that broke. Accepted, and marked so it can be counted.
    soup = ("налог сбор плательщик ведомость " * 10).encode("cp1251").decode("latin-1")
    path, flags, _ = decide(pi_markdown=_sane_cyrillic(), reasons=set(), reference=soup,
                            layer_chars=400, blank=False)
    assert path == "accept"
    assert "gate_fired_ref_insane" in flags


def test_both_sides_garbage_without_the_gate_is_corrupt():
    # Rule 8: the gate does not fire because both texts lost the same thing.
    soup = ("налог сбор плательщик ведомость " * 10).encode("cp1251").decode("latin-1")
    path, _, _ = decide(pi_markdown=soup, reasons=set(), reference=soup,
                        layer_chars=400, blank=False)
    assert path == "corrupt"


def test_empty_candidate_with_an_empty_reference_is_not_accepted_empty():
    # pdfium sees characters, pypdf returns nothing, pdf-inspector returns
    # nothing: the page is not silently accepted as empty.
    path, _, _ = decide(pi_markdown="", reasons=set(), reference="", layer_chars=50, blank=False)
    assert path == "corrupt"


# --- failures ------------------------------------------------------------------------

def test_without_pypdf_the_route_falls_back_to_pdfium_and_says_so(tmp_path, monkeypatch):
    """pdf-inspector read the file, pypdf did not: no silent loss, no silence.

    Fails if the route goes on without a reference (verified: the frames page,
    which pdf-inspector empties, was then routed corrupt instead of being
    recovered) or if the flag is dropped.
    """
    monkeypatch.setattr(pdf_route, "open_reference", lambda path: None)

    routes = _route(tmp_path, rf.one(rf.box_drawing_form_page()))

    assert routes[0].path == "substitute"
    assert routes[0].source == "pdfium"
    assert "reference_unavailable" in routes[0].flags


def test_a_password_protected_pdf_is_refused_by_name(tmp_path):
    """The user password case: a clear message, not a traceback or empty output.

    Fails if pdf-inspector's exception escapes the route unwrapped (verified:
    the message lost "password required").
    """
    import pypdf

    writer = pypdf.PdfWriter(clone_from=io.BytesIO(rf.one(rf.cyrillic_prose_page())))
    writer.encrypt(user_password="secret", owner_password="owner", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    pdf = tmp_path / "locked.pdf"
    pdf.write_bytes(buffer.getvalue())

    with pytest.raises(ConversionError, match="password required"):
        convert_path(pdf)


def test_conversion_result_carries_the_routes(tmp_path):
    pdf = tmp_path / "mixed.pdf"
    pdf.write_bytes(rf.mixed_route_document())

    result = convert_path(pdf)

    assert result.units == 7
    assert [p.path for p in result.pages] == [rf.MIXED_EXPECTED[n] for n in range(1, 8)]
    assert result.text == render_markdown(list(result.pages))


def test_summary_line_counts_paths_and_prices_review(tmp_path):
    routes = _route(tmp_path, rf.mixed_route_document())
    line = pdf_route.summary_line(routes)
    assert line.startswith("7 pages: 1 accept, 2 substitute, 2 scan, 1 corrupt, 1 blank; 3 need review")
    assert "$0.12" in line
