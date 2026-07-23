"""Minimal PDFs built by hand, reproducing the defects measured on the real corpus.

The real documents that exposed these are third-party copyrighted files and are
deliberately not in this repo. See docs/pdf-engine.md.
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


def _build_multipage_pdf(streams: list[str]) -> bytes:
    """Multi-page sibling of _build_pdf: one page per content stream, sharing a
    single font. _build_pdf hardwires Count 1 / Kids [3 0 R], so it cannot
    express per-page behaviour; this builder is what lets a fixture put a text
    layer on one page and none on the next (the measured partial-loss shape).
    """
    n = len(streams)
    page_objs = [4 + 2 * i for i in range(n)]
    kids = " ".join(f"{p} 0 R" for p in page_objs)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [" + kids.encode() + b"] /Count " + str(n).encode() + b" >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for i, content_stream in enumerate(streams):
        content_obj = 5 + 2 * i
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 3 0 R >> >> /Contents "
            + str(content_obj).encode() + b" 0 R >>"
        )
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


def image_only_page() -> bytes:
    """Graphics, no text operators: page.chars == []. Stands in for a scanned
    page -- the engine has no OCR, so it extracts nothing."""
    return _build_pdf(_cell_rect(100, 100, 400, 200))


def text_then_image() -> bytes:
    """Two pages: prose on page 1, an image-only page on page 2. Reproduces the
    21 partially-empty documents -- page 1's text must survive while page 2 is
    marked, not silently dropped."""
    return _build_multipage_pdf([
        _text(72, 700, "Just a paragraph, no ruling lines anywhere."),
        _cell_rect(100, 100, 400, 200),
    ])


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


def cell_nested_in_a_spanning_cell() -> bytes:
    """One grid whose column divider stops short, so pdfplumber reports a cell
    INSIDE another cell of the same table.

    The top band has a vertical divider that reaches only the short rule at
    Y_SPLIT, not the band's lower edge. pdfplumber's cell derivation anchors one
    rectangle per intersection, so it emits both the whole band
    (X0,Y_MID)-(X1,Y_TOP) and the small (XM,Y_SPLIT)-(X1,Y_TOP) sitting inside
    it. `Table.extract()` reads each rectangle independently, so "4242" lands in
    two cells of the same rendered row.

    This is not a hypothetical: across both private corpora it accounted for
    every duplicated digit the engine produced (3138 of them, on 27 of 893
    documents), and it is the reason `_extract_rows` subtracts a child cell's
    chars from its parent.
    """
    X0, XM, X1 = 72, 200, 320
    Y_TOP, Y_SPLIT, Y_MID, Y_BOT = 700, 676, 652, 628

    cs = ""
    for y in (Y_TOP, Y_MID, Y_BOT):
        cs += _line(X0, y, X1, y)
    cs += _line(X0, Y_BOT, X0, Y_TOP)
    cs += _line(X1, Y_BOT, X1, Y_TOP)
    # Stops at Y_SPLIT rather than Y_MID -- this is the whole point of the
    # fixture. Carried to Y_MID, pdfplumber resolves a clean rowspan instead and
    # no cell nests inside another.
    cs += _line(XM, Y_SPLIT, XM, Y_TOP)
    cs += _line(XM, Y_SPLIT, X1, Y_SPLIT)
    cs += _line(XM, Y_BOT, XM, Y_MID)

    cs += _text(X0 + 4, Y_SPLIT + 8, "Header")
    cs += _text(XM + 4, Y_SPLIT + 8, "4242")   # inside BOTH the band and the small cell
    cs += _text(X0 + 4, Y_MID + 8, "1717")     # inside the band only
    cs += _text(X0 + 4, Y_BOT + 8, "Total")
    cs += _text(XM + 4, Y_BOT + 8, "5959")
    return _build_pdf(cs)


# -- Two-column reading order -------------------------------------------------
# The engine ordered prose by vertical position alone, so a page with two
# columns was read straight across the gutter. These fixtures reproduce that
# geometry the way the corpus measurement sees it: projected onto 60 x-bins,
# the empty band between the columns is several bins wide and its centre sits
# in the middle 40% of the page.
COL_LEFT_X = 72
COL_RIGHT_X = 340
COL_TOP_Y = 700
COL_DY = 16


def _column_block(x, tag, n_rows, n_words=4, y0=COL_TOP_Y, dy=COL_DY):
    """Rows of tagged words at a fixed left edge. Every word is unique, so a
    test can assert on ordering, on survival and on duplication separately.
    """
    cs = ""
    for r in range(n_rows):
        words = " ".join(f"{tag}{r}{chr(ord('a') + w)}" for w in range(n_words))
        cs += _text(x, y0 - r * dy, words)
    return cs


def two_column_page() -> bytes:
    """Ten rows of prose in two columns, each row's two halves sharing a
    baseline.

    `extract_text_lines` groups by vertical position across the full page
    width, so every one of these rows comes back as a single line holding both
    columns. That is the measured defect: over 891 documents / 6697 pages the
    detector fires on 213 pages, 83 of which are two-column prose, and scored
    against the engine's own output those pages carried 910 fused lines.
    """
    return _build_pdf(_column_block(COL_LEFT_X, "left", 10)
                      + _column_block(COL_RIGHT_X, "right", 10))


def two_column_with_spanning_table() -> bytes:
    """The same two-column prose, plus a ruled grid spanning BOTH columns.

    The page is two-column by the detector's own verdict, so this fixture
    isolates the guard rather than the detection: splitting the page along the
    gutter would tear the table in half, so the verdict must be discarded and
    single-column order kept for the whole page.
    """
    cs = _column_block(COL_LEFT_X, "left", 10) + _column_block(COL_RIGHT_X, "right", 10)
    labels = [["spanA0", "spanB0"], ["spanA1", "spanB1"]]
    for r in range(2):
        for c in range(2):
            x, y = 72 + c * 234, 460 - r * 24
            cs += _cell_rect(x, y, 234, 24)
            cs += _text(x + 4, y + 8, labels[r][c])
    return _build_pdf(cs)


def single_column_dense() -> bytes:
    """An ordinary single-column page, well over the detector's 60-word floor.

    97% of corpus pages look like this and not one of them may move, so this
    is the fixture the byte-identity assertion is anchored on.
    """
    return _build_pdf(_column_block(72, "line", 15, n_words=8))


def wide_gap_but_one_side_empty() -> bytes:
    """A wide, centred empty band that is NOT a column boundary: everything to
    the right of it is two stray words -- a page number, a margin note. Each
    side must hold at least a quarter of the page's word mass; this one holds
    about 3%, so the band is a margin, not a gutter.
    """
    cs = _column_block(COL_LEFT_X, "left", 15)
    cs += _text(COL_RIGHT_X, COL_TOP_Y, "strayone")
    cs += _text(COL_RIGHT_X, COL_TOP_Y - COL_DY, "straytwo")
    return _build_pdf(cs)


def two_columns_but_too_few_words() -> bytes:
    """Textbook two-column geometry, but only 24 words on the page -- under the
    60-word floor, below which the projection is too sparse to call a gutter
    apart from ordinary ragged whitespace.
    """
    return _build_pdf(_column_block(COL_LEFT_X, "left", 3)
                      + _column_block(COL_RIGHT_X, "right", 3))


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
