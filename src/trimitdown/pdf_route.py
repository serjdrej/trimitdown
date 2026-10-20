"""The PDF route: pdf-inspector, checked page by page against an independent decoder.

pdf-inspector gives the best structure we measured (headings, tables without
rules) and the fewest tokens, and it also loses text without saying so: whole
pages come back empty while the text layer is intact, and on a few pages
Cyrillic comes back as Latin with no flag at all. So every page is checked and
sent down one of five paths:

  accept      pdf-inspector's markdown, byte for byte
  substitute  pdf-inspector lost text the layer still has: pypdf's plain text
  scan        no text layer, or an OCR layer under a page image
  corrupt     a text layer every decoder reads as garbage
  blank       no text layer and nothing drawn on the page

The order of the checks is the routing table of the 0.2 design review (§2.2),
with one correction recorded there: when the gate fires and the reference is
garbage, the page is accepted only if pdf-inspector's own text is sane --
garbage on both sides goes to review rather than through silently.

Page numbers here are 1-based everywhere: in the owner's review rule, in
pdf-inspector's ocr_reasons_by_page and pages_needing_ocr. Only
PageMarkdown.page counts from 0, and _page_number() is the one place that
converts.

This module must not import FastAPI or anything that writes files: it is part
of the pure conversion layer (tests/test_convert_pure.py).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from trimitdown.text_metrics import (
    gate_fires,
    is_sane,
    letter_counts,
    strip_box_drawing,
)

# Reasons pdf-inspector gives for a page whose text is an OCR layer. Both are
# needed: "scanned" is what the measured FineReader documents carried, and the
# synthetic FineReader shape (full-page image, Tr 3 text) gets
# "invisible_text_layer" instead. A page needing OCR with no reason at all is
# handled by the layer check, not by this set.
SCAN_REASONS = frozenset({"scanned", "invisible_text_layer"})

PATHS = ("accept", "substitute", "scan", "corrupt", "blank")
REVIEW_PATHS = frozenset({"scan", "corrupt"})

# Measured price of review per page: the owner's arm 3 (Tesseract, then Sonnet
# at medium effort reconciling against the image) cost $0.036-0.038 a page on 57
# pages. Rounded up; it grows faster than linearly on long documents.
REVIEW_COST_PER_PAGE_USD = 0.04

# A page with no text layer is blank when, rendered at BLANK_DPI, fewer than
# BLANK_MAX_INK_SHARE of its pixels are darker than BLANK_INK_LEVEL. The owner's
# rule: zero characters in the layer does not mean the page is empty -- look at
# the image. Loose on purpose: scanner noise sends a page to review, never the
# other way round.
BLANK_DPI = 30
BLANK_INK_LEVEL = 224
BLANK_MAX_INK_SHARE = 0.0005


class PdfUnreadable(ValueError):
    """pdf-inspector could not open the file. The message says why."""


@dataclass(frozen=True)
class PageRoute:
    page: int                 # 1-based
    path: str                 # one of PATHS
    reasons: tuple[str, ...]  # pdf-inspector's reasons for this page
    text: str                 # what this page contributes to the plain document
    layer_text: str = ""      # the text layer as the reference decoder read it
    source: str = "pdf_inspector"  # pdf_inspector | pypdf | pdfium | ocr_layer | none
    flags: tuple[str, ...] = ()
    metrics: dict = field(default_factory=dict, compare=False)

    @property
    def needs_review(self) -> bool:
        return self.path in REVIEW_PATHS


def _page_number(pdf_inspector_page: int) -> int:
    """PageMarkdown.page counts from 0; everything else here counts from 1."""
    return pdf_inspector_page + 1


def scan_marker(page: int) -> str:
    return f"[trimitdown: page {page} has no usable text layer (scan)]\n"


def corrupt_marker(page: int) -> str:
    return f"[trimitdown: page {page} has no usable text layer (corrupt)]\n"


def ocr_layer_note(page: int) -> str:
    return f"[trimitdown: page {page}: OCR layer, not verified]\n"


def _with_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def decide(
    *,
    pi_markdown: str,
    reasons: set[str] | frozenset[str],
    reference: str,
    layer_chars: int,
    blank: bool,
) -> tuple[str, tuple[str, ...], dict]:
    """The routing table. Pure: no file is opened here. (path, flags, details)."""
    details: dict = {}
    if layer_chars == 0:
        return ("blank" if blank else "scan"), (), details
    if reasons & SCAN_REASONS:
        return "scan", (), details

    ref_sane, ref_why = is_sane(reference)
    details["ref_sane"] = ref_why or "ok"
    has_reference = bool(reference.strip())

    if not pi_markdown.strip():
        # pdf-inspector returned nothing while the layer has characters. Not
        # subject to the gate's 20-letter floor: an empty page with six letters
        # in its layer is still a lost page.
        if has_reference and ref_sane:
            return "substitute", (), details
        return "corrupt", (), details

    fired, gate = gate_fires(pi_markdown, reference)
    details["gate"] = gate
    pi_sane, pi_why = is_sane(pi_markdown)
    details["pi_sane"] = pi_why or "ok"

    if fired:
        if ref_sane:
            return "substitute", ("gate_fired",), details
        if pi_sane:
            return "accept", ("gate_fired", "gate_fired_ref_insane"), details
        return "corrupt", ("gate_fired",), details
    if not pi_sane and not ref_sane:
        return "corrupt", (), details
    return "accept", (), details


def _body(page: int, path: str, pi_markdown: str, layer_text: str) -> tuple[str, str]:
    """(text for the plain document, source of that text)."""
    if path == "accept":
        return pi_markdown, "pdf_inspector"
    if path == "substitute":
        return _with_newline(strip_box_drawing(layer_text)), "reference"
    if path == "scan" and layer_text.strip():
        return ocr_layer_note(page) + _with_newline(strip_box_drawing(layer_text)), "ocr_layer"
    if path == "scan":
        return scan_marker(page), "none"
    if path == "corrupt":
        return corrupt_marker(page), "none"
    return "", "none"


def _looks_blank(pdfium_page) -> bool:
    bitmap = pdfium_page.render(scale=BLANK_DPI / 72, grayscale=True)
    image = bitmap.to_pil().convert("L")
    histogram = image.histogram()
    ink = sum(histogram[:BLANK_INK_LEVEL])
    return ink / max(image.width * image.height, 1) < BLANK_MAX_INK_SHARE


def open_reference(path: str):
    """pypdf reader, or None when pypdf cannot read the file at all."""
    import pypdf

    # pypdf reports recoverable structure problems through logging; on a
    # damaged but readable file that is a wall of warnings in a CLI's stderr.
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = pypdf.PdfReader(path)
        if reader.is_encrypted:
            reader.decrypt("")
        return reader
    except Exception:
        return None


def route_pdf(path: str | Path) -> list[PageRoute]:
    """Route every page of a PDF on disk. Raises PdfUnreadable for files
    pdf-inspector cannot open (not a PDF, damaged, encrypted with a password)."""
    import pdf_inspector
    import pypdfium2

    path = str(path)
    try:
        result = pdf_inspector.extract_pages_markdown(path)
    except Exception as e:
        message = str(e)
        if "encrypt" in message.lower():
            raise PdfUnreadable("the PDF is encrypted, password required") from e
        raise PdfUnreadable(message or type(e).__name__) from e

    reasons_by_page: dict[int, set[str]] = {}
    for entry in result.ocr_reasons_by_page:
        reasons_by_page.setdefault(entry.page, set()).update(entry.reasons)

    reader = open_reference(path)
    try:
        pdfium_doc = pypdfium2.PdfDocument(path)
    except Exception:
        pdfium_doc = None

    routes = []
    try:
        for pi_page in result.pages:
            number = _page_number(pi_page.page)
            reasons = set(reasons_by_page.get(number, ()))
            if pi_page.ocr_reason:
                reasons.add(pi_page.ocr_reason)
            flags: list[str] = []

            pdfium_page = pdfium_text = None
            if pdfium_doc is not None:
                try:
                    pdfium_page = pdfium_doc[pi_page.page]
                    textpage = pdfium_page.get_textpage()
                    pdfium_text = textpage.get_text_range()
                    textpage.close()
                except Exception:
                    pdfium_page = pdfium_text = None
            if pdfium_text is None:
                flags.append("layer_unavailable")

            reference = None
            if reader is not None:
                try:
                    reference = reader.pages[pi_page.page].extract_text() or ""
                except Exception:
                    reference = None
            reference_source = "pypdf"
            if reference is None:
                # pdf-inspector read the file and pypdf did not. Fall back to
                # pdfium rather than to nothing: with no reference at all an
                # emptied page would pass as accepted, which is the loss this
                # route exists to catch. Flagged, never silent.
                flags.append("reference_unavailable")
                reference = pdfium_text or ""
                reference_source = "pdfium"

            if pdfium_text is not None:
                layer_chars = sum(1 for ch in pdfium_text if not ch.isspace())
            else:
                layer_chars = sum(1 for ch in reference if not ch.isspace())

            blank = False
            if layer_chars == 0 and pdfium_page is not None:
                try:
                    blank = _looks_blank(pdfium_page)
                except Exception:
                    blank = False

            markdown = pi_page.markdown or ""
            path_name, decided_flags, details = decide(
                pi_markdown=markdown,
                reasons=reasons,
                reference=reference,
                layer_chars=layer_chars,
                blank=blank,
            )
            flags.extend(decided_flags)
            text, source = _body(number, path_name, markdown, reference)
            if source == "reference":
                source = reference_source
            metrics = {
                "pi_letters": sum(letter_counts(markdown).values()),
                "ref_letters": sum(letter_counts(reference).values()),
                "layer_chars": layer_chars,
                "needs_ocr": bool(pi_page.needs_ocr),
                **details,
            }
            routes.append(PageRoute(
                page=number,
                path=path_name,
                reasons=tuple(sorted(reasons)),
                text=text,
                layer_text=reference,
                source=source,
                flags=tuple(flags),
                metrics=metrics,
            ))
            if pdfium_page is not None:
                pdfium_page.close()
    finally:
        if pdfium_doc is not None:
            pdfium_doc.close()
    return routes


PAGE_ANCHOR = "<!-- page {} -->\n"


def render_markdown(routes: list[PageRoute], *, page_anchors: bool = False) -> str:
    """The document: page bodies joined the way the benchmark joined
    pdf-inspector's pages, so an all-accept document is byte-identical to it.

    With page_anchors each page starts with ``<!-- page N -->`` -- the format of
    a review directory's document.md, built here so the two cannot drift. A
    citation needs "page N"; the plain join cannot give it.
    """
    if page_anchors:
        return "\n\n".join(PAGE_ANCHOR.format(route.page) + route.text for route in routes)
    return "\n\n".join(route.text for route in routes)


def pdf_to_markdown(path: str | Path) -> str:
    return render_markdown(route_pdf(path))


def path_counts(routes: list[PageRoute]) -> dict[str, int]:
    counts = {name: 0 for name in PATHS}
    for route in routes:
        counts[route.path] += 1
    return counts


def summary_line(routes: list[PageRoute], review_pages: int | None = None) -> str:
    """'7 pages: 1 accept, 2 substitute, 2 scan, 1 corrupt, 1 blank; ...'"""
    counts = path_counts(routes)
    parts = ", ".join(f"{counts[name]} {name}" for name in PATHS)
    if review_pages is None:
        review_pages = sum(1 for route in routes if route.needs_review)
    cost = review_pages * REVIEW_COST_PER_PAGE_USD
    noun = "page" if len(routes) == 1 else "pages"
    return (
        f"{len(routes)} {noun}: {parts}; {review_pages} need review "
        f"(about ${cost:.2f} at ${REVIEW_COST_PER_PAGE_USD:.2f}/page)"
    )
