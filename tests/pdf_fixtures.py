"""Minimal PDFs built by hand, reproducing the defects measured on the real corpus.

The real documents that exposed these are third-party copyrighted files and are
deliberately not in this repo. See
docs/superpowers/specs/2026-07-16-pdf-extraction-diagnosis.md.
"""

FONT_SIZE = 10.56
GAP_PT = 2.89  # measured inter-word gap on the real corpus: 2.89-2.93pt
# TJ offsets are thousandths of an em and are *subtracted* from the displacement,
# so a negative number moves the next glyph forward.
GAP_TJ = round(-GAP_PT / FONT_SIZE * 1000)  # -274 -> 2.893pt

# A small font size with a gap that is tiny in absolute points but normal
# relative to the font size -- the measured Russian-patent case (§13 of the
# design doc). At this font size, ratio 0.12 * 6.0 = 0.72pt sits just under the
# 0.738pt gap below, so a *ratio* threshold correctly splits the words. A fixed
# absolute threshold of 2pt (the pre-revision design) does not: 0.738 < 2, so it
# stays glued. This fixture exists to prove the ratio does something an
# absolute value cannot, not just a smaller version of the same thing.
FONT_SIZE_SMALL = 6.0
GAP_PT_SMALL = 0.74
GAP_TJ_SMALL = round(-GAP_PT_SMALL / FONT_SIZE_SMALL * 1000)


def _build_pdf(content_stream: str) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    stream = content_stream.encode("latin-1")
    objects.append(
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
    )

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
    )
    return bytes(out)


def _text(x, y, s, size=FONT_SIZE):
    return f"BT /F1 {size} Tf {x} {y} Td ({s}) Tj ET\n"


def _cell_rect(x, y, w, h):
    return f"{x} {y} {w} {h} re S\n"


def _line(x0, y0, x1, y1):
    return f"{x0} {y0} m {x1} {y1} l S\n"


def gapped_words() -> bytes:
    """Two words separated only by a TJ offset — no space character exists."""
    return _build_pdf(f"BT /F1 {FONT_SIZE} Tf 72 700 Td [(different) {GAP_TJ} (stationary)] TJ ET\n")


def gapped_words_small_font() -> bytes:
    """Same shape as gapped_words(), but at a small font size where the gap is
    tiny in absolute points (0.738pt) yet normal relative to the font size.
    Reproduces the Russian-patent measurement from §13 of the design doc: no
    single absolute x_tolerance satisfies both this file and gapped_words().
    """
    return _build_pdf(
        f"BT /F1 {FONT_SIZE_SMALL} Tf 72 700 Td "
        f"[(different) {GAP_TJ_SMALL} (stationary)] TJ ET\n"
    )


def ruled_table() -> bytes:
    """Prose, then a 3x2 grid drawn with stroked cell rectangles."""
    cs = _text(72, 720, "Intro prose above the table.")
    labels = [["Header A", "Header B"], ["a1", "b1"], ["a2", "b2"]]
    for r in range(3):
        for c in range(2):
            x, y = 72 + c * 120, 660 - r * 24
            cs += _cell_rect(x, y, 120, 24)
            cs += _text(x + 4, y + 8, labels[r][c])
    return _build_pdf(cs)


def kv_table() -> bytes:
    """A single-row grid — the shape all 21 of the bike-shop file's tables have."""
    cs = ""
    for c, label in enumerate(["Frame type:", "Aluminium"]):
        x, y = 72 + c * 120, 660
        cs += _cell_rect(x, y, 120, 24)
        cs += _text(x + 4, y + 8, label)
    return _build_pdf(cs)


def pipe_cell() -> bytes:
    """A grid with a literal pipe in a body cell."""
    cs = ""
    labels = [["Head", "Other"], ["a|b", "plain"]]
    for r in range(2):
        for c in range(2):
            x, y = 72 + c * 120, 660 - r * 24
            cs += _cell_rect(x, y, 120, 24)
            cs += _text(x + 4, y + 8, labels[r][c])
    return _build_pdf(cs)


def pipe_in_single_row() -> bytes:
    """A single-row grid with a literal pipe. Single-row grids render as prose,
    where an escaped "\\|" would show a visible backslash that isn't in the
    source document — escaping must happen only at grid render, not sooner.
    """
    cs = ""
    for c, label in enumerate(["a|b", "plain"]):
        x, y = 72 + c * 120, 660
        cs += _cell_rect(x, y, 120, 24)
        cs += _text(x + 4, y + 8, label)
    return _build_pdf(cs)


def framed_prose() -> bytes:
    """A page border (rectangle) plus one intersecting horizontal rule — the
    shape of a page frame, a "Note" callout, or an invoice box. find_tables
    sees a 1-column, 2-row grid; it must render as prose, not a table, exactly
    like the existing single-row case.
    """
    x, y, w, h = 72, 600, 300, 100
    cs = _cell_rect(x, y, w, h)
    mid_y = y + h / 2
    cs += _line(x, mid_y, x + w, mid_y)
    cs += _text(x + 4, y + h - 30, "First paragraph inside the frame.")
    cs += _text(x + 4, y + 20, "Second paragraph inside the frame.")
    return _build_pdf(cs)


def blank_row_table() -> bytes:
    """A grid with a ruled but empty spacer row — common in real ruled tables."""
    cs = ""
    labels = {0: ["Head", "Other"], 2: ["a1", "b1"]}
    for r in range(3):
        for c in range(2):
            x, y = 72 + c * 120, 660 - r * 24
            cs += _cell_rect(x, y, 120, 24)
            if r in labels:
                cs += _text(x + 4, y + 8, labels[r][c])
    return _build_pdf(cs)


def prose_only() -> bytes:
    """No ruling lines — markitdown wrapped this kind of page in 104 fake table rows."""
    return _build_pdf(_text(72, 700, "Just a paragraph, no ruling lines anywhere."))


def offset_pdf_marker() -> bytes:
    """A real, valid PDF whose %PDF marker sits a few bytes into the file
    instead of at byte 0 -- reproduces the measured corpus case (a leading
    \\r\\n before the header). pdfplumber/pdfminer scan for the marker rather
    than anchor at byte 0, so this parses exactly like any other PDF; a
    byte-0-anchored signature check would misroute it to markitdown.
    """
    return b"\r\n" + _build_pdf(_text(72, 700, "Real PDF content with an offset header."))


def frame_with_nested_table() -> bytes:
    """An outer frame rectangle (with an intersecting rule, so find_tables sees
    a 2-row x 1-col grid) whose interior holds a paragraph plus a real 3x2
    ruled data table -- the acceptance-anchor shape in miniature. The frame must be
    dropped as a layout frame (single-column -> fails is_real_table) while
    its child, the real inner grid, is kept and rendered as a table; the
    frame's paragraph must survive as prose, not vanish or duplicate.
    """
    fx, fy, fw, fh = 72, 400, 400, 260
    cs = _cell_rect(fx, fy, fw, fh)
    mid_y = fy + fh / 2
    cs += _line(fx, mid_y, fx + fw, mid_y)
    cs += _text(fx + 4, fy + fh - 20, "This is a paragraph in the frame.")

    labels = [["Header A", "Header B"], ["innercellA1", "innercellB1"], ["a2", "b2"]]
    ix, iy = fx + 20, fy + 20
    for r in range(3):
        for c in range(2):
            x, y = ix + c * 120, iy + 48 - r * 24
            cs += _cell_rect(x, y, 120, 24)
            cs += _text(x + 4, y + 8, labels[r][c])
    return _build_pdf(cs)


def real_table_with_nested_table() -> bytes:
    """An outer frame that is ITSELF a real ruled table (2 cols, header + one
    data row -- passes is_real_table on its own merits, unlike
    frame_with_nested_table()'s single-column frame), plus a large undivided
    spacer band below the data row that holds a fully separate, real 3x2
    ruled data table well inset from every outer line. find_tables returns
    two grids and BOTH pass is_real_table -- classification alone cannot
    tell them apart. Only the containment backstop in _render_page (the
    outer's bbox encloses the inner's) drops the outer and keeps the inner.
    Without this fixture, that backstop has zero coverage: the only existing
    nested fixture is dropped at classification, before the backstop runs.
    """
    fx, fy, fw, fh = 72, 400, 400, 300
    row01_y = fy + fh - 40   # header/data-row boundary
    row12_y = fy + fh - 80   # data-row/spacer boundary
    mid_x = fx + fw / 2

    cs = _cell_rect(fx, fy, fw, fh)  # outer perimeter
    cs += _line(fx, row01_y, fx + fw, row01_y)
    cs += _line(fx, row12_y, fx + fw, row12_y)
    cs += _line(mid_x, row12_y, mid_x, fy + fh)  # column divider, header+data rows only

    cs += _text(fx + 10, row01_y + 12, "FrameCol1")
    cs += _text(mid_x + 10, row01_y + 12, "FrameCol2")
    cs += _text(fx + 10, row12_y + 12, "framerowA")
    cs += _text(mid_x + 10, row12_y + 12, "framerowB")

    labels = [["InnerColA", "InnerColB"], ["nestedcell1", "nestedcell2"], ["x2", "y2"]]
    ix, iy = fx + 40, fy + 40
    for r in range(3):
        for c in range(2):
            x, y = ix + c * 120, iy + 48 - r * 24
            cs += _cell_rect(x, y, 120, 24)
            cs += _text(x + 4, y + 8, labels[r][c])

    return _build_pdf(cs)


def gapped_words_in_cell() -> bytes:
    """A ruled 1x2 grid whose second cell has two words separated only by a
    TJ offset -- no space character. `find_tables` propagates text settings
    only if the caller passes them again at `Table.extract()` time; if a call
    site drops `**TEXT_SETTINGS`, this cell's words come back glued even
    though prose text elsewhere in the document is correctly split.
    """
    cs = _cell_rect(72, 660, 120, 24)
    cs += _cell_rect(192, 660, 120, 24)
    cs += _text(72 + 4, 660 + 8, "Header")
    cs += (
        f"BT /F1 {FONT_SIZE} Tf {192 + 4} {660 + 8} Td "
        f"[(different) {GAP_TJ} (stationary)] TJ ET\n"
    )
    return _build_pdf(cs)
