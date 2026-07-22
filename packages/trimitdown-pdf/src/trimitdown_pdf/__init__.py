"""Table-detection stage for ruled PDF grids, on top of pdfplumber.

pdfplumber's find_tables answers "where are ruled cells?", never "is this a
table?" — so a page frame crossed by any rule comes back as a grid. This
package adds the missing validation stage (`is_real_table`), plus a
ready-made whole-document renderer (`pdf_to_markdown`) built on it.

Scope is deliberately narrow: `vertical_strategy: "lines"` only. Borderless
tables are not detected at all, and there is no OCR — scanned pages yield
nothing. See docs/pdf-engine.md in the TrimItDown repository for the design,
the measurements and how to reproduce them.

API is unstable until 1.0.
"""

from io import BytesIO
from pathlib import Path

import pdfplumber
from pdfplumber.utils import extract_text

__all__ = [
    "pdf_to_markdown",
    "is_real_table",
    "TABLE_SETTINGS",
    "TEXT_SETTINGS",
    "X_TOLERANCE_RATIO",
]

__version__ = "0.1.0"

# Fraction of font size, not an absolute point value. An absolute point
# threshold cannot port across font sizes: the original corpus needed <2.89pt,
# a Russian patent in the wider 698-file sweep needs <0.74pt, and no single
# absolute number satisfies both. Chosen by measuring both failure directions
# across 136 files -- glued words (threshold too high) and words torn apart
# from the inside (too low). 0.12 ties 0.15 on glue and stays clear of the
# over-split knee below 0.10.
X_TOLERANCE_RATIO = 0.12
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
TEXT_SETTINGS = {"x_tolerance_ratio": X_TOLERANCE_RATIO}
# When x_tolerance_ratio is set, pdfplumber ignores x_tolerance entirely --
# every extraction call site (page text *and* table cells) must pass the
# ratio, or that call silently reverts to the 3pt default and re-glues words.


def _cell_text(value: str | None) -> str:
    # Pipe escaping happens at grid render time, not here: single-row and
    # single-column grids emit prose, where a "\|" would show a visible
    # backslash that isn't in the source document.
    return (value or "").replace("\n", " ").strip()


def _escape_pipe(value: str) -> str:
    return value.replace("|", "\\|")


def _row_is_filled(row: list[str]) -> bool:
    return sum(1 for c in row if c.strip()) >= 2


def is_real_table(rows: list[list[str]]) -> bool:
    """The detection stage: is this ruled grid a table, or a layout frame?

    pdfplumber's find_tables answers "where are ruled cells?", never "is this a
    table?" — so a page frame crossed by any rule comes back as a grid. This is
    Nurminen's detection criterion (tabula-java NurminenDetectionAlgorithm) on
    pdfplumber's cells: a table needs at least two rows in which at least two
    columns hold content, and those rows must be the majority of rows that have
    any content at all. Evaluated against a 74-grid hand-labeled set: keeps
    44/45 real tables, drops 13/14 layout frames. Geometry (cell length,
    coverage, empty fraction) was tried and destroys 29-49% of real tables;
    see docs/pdf-engine.md.
    """
    if len(rows) < 2 or len(rows[0]) < 2:
        return False
    rows_with_content = [r for r in rows if any(c.strip() for c in r)]
    if not rows_with_content:
        return False
    filled = sum(1 for r in rows_with_content if _row_is_filled(r))
    return filled >= 2 and filled / len(rows_with_content) >= 0.5


# Diagram-debris filter. find_tables sometimes returns a grid that is chart/diagram
# leftover, not a table; rowfill keeps 7 of 15 such grids in the labeled set. A
# graphics-overlap signal (curves-in-bbox) was measured and REJECTED — it drops all
# 7 but also kills 4 real tables that legitimately contain graphics. The one signal
# that fired cleanly: heavy rotated text. Real tables have <=3% rotated chars (OCR
# noise); debris charts have 17-49%. rot>=0.15 drops 2 of the 7 debris grids and 0
# real tables. It is a partial win — the other 5 stay (measured-open, see deferred).
X_ROT_DEBRIS = 0.15


def _is_diagram_debris(page, table) -> bool:
    x0, top, x1, bottom = table.bbox
    chars = [c for c in page.chars
             if x0 <= (c["x0"] + c["x1"]) / 2 <= x1 and top <= (c["top"] + c["bottom"]) / 2 <= bottom]
    if not chars:
        return False
    rotated = sum(1 for c in chars if not c.get("upright", True))
    return rotated / len(chars) >= X_ROT_DEBRIS


def _char_in(char, bbox) -> bool:
    # Same midpoint test, and the same half-open edges, that pdfplumber's
    # Table.extract uses to assign a char to a cell. Matching it exactly is the
    # point: _extract_rows subtracts one of its results from another.
    x0, top, x1, bottom = bbox
    return (x0 <= (char["x0"] + char["x1"]) / 2 < x1
            and top <= (char["top"] + char["bottom"]) / 2 < bottom)


def _encloses(outer, inner) -> bool:
    ox0, ot, ox1, ob = outer
    ix0, it, ix1, ib = inner
    if (ox1 - ox0) * (ob - ot) <= (ix1 - ix0) * (ib - it):
        return False
    return ox0 <= ix0 and ot <= it and ox1 >= ix1 and ob >= ib


def _extract_rows(page, table) -> list[list[str | None]]:
    """Cell text for one grid, with nested cells subtracted from their parent.

    pdfplumber reports one rectangle per cell, and those rectangles overlap
    wherever a ruling line stops short: the spanning cell keeps its full extent
    while the cells it covers are still reported separately. Table.extract()
    reads each rectangle independently, so every char in the overlap is emitted
    once per rectangle -- the same value twice in one rendered row. Measured
    over all 893 documents of the private corpora, this accounted for every
    duplicated digit either engine produced: 3138 before, 0 after, on 27
    documents, with no document made worse on either parity row.

    So the parent cell is re-extracted from its own chars minus the chars its
    children already claim. Cells with no children keep Table.extract's text
    verbatim, which is the overwhelming majority of them.
    """
    rows = table.extract(**TEXT_SETTINGS)
    # Table.rows is a property that rebuilds the row model from scratch on every
    # access, so it is read once here and reused.
    table_rows = table.rows
    cells = {c for row in table_rows for c in row.cells if c}
    nested = {c: [d for d in cells if d != c and _encloses(c, d)] for c in cells}
    nested = {c: inner for c, inner in nested.items() if inner}
    if not nested:
        return rows

    for ri, row in enumerate(table_rows):
        for ci, cell in enumerate(row.cells):
            inner = nested.get(cell) if cell else None
            if not inner:
                continue
            chars = [ch for ch in page.chars
                     if _char_in(ch, cell) and not any(_char_in(ch, d) for d in inner)]
            rows[ri][ci] = extract_text(chars, **TEXT_SETTINGS) if chars else ""
    return rows


# Reading order on two-column pages. Prose was ordered by vertical position
# alone, so a two-column page was read straight across the gutter and the two
# columns fused into single lines. Measured over 891 documents / 6697 pages:
# the detector fires on 213 pages (3.2%) across 80 documents (9.0%).
#
# Of those 213, only 83 are two-column prose. On the other 130 the "gutter" is
# a wide ruled table's own column gap -- a mean 86% of the words on those pages
# sit inside an accepted grid -- and the guard below refuses to split them.
# Scored against this engine's output, the defect was 910 fused prose lines,
# 673 of them on the 83 split pages and 1 left afterwards. An earlier pass
# reported 5702 fused lines of 11185; that counted geometric word-lines over
# the raw page, so every row of a wide table scored as fused even though the
# engine had already rendered it as grid rows. Same detector, same 213 pages --
# the number moved 6x because the thing being counted changed.
#
# The constants below are the detector that produced those numbers, ported
# rather than re-derived: a fix tuned to a different definition of
# "two-column" than the measurement's would make the before/after numbers
# meaningless. Word bboxes are projected onto 60 x-bins; the widest empty band
# whose centre sits in the middle 40% of the page is the gutter candidate, and
# it is accepted only if each side holds at least a quarter of the word mass.
# The 60-word floor is what stops a sparse page's ordinary ragged whitespace
# from reading as a column boundary.
COLUMN_BINS = 60
COLUMN_MIN_WORDS = 60
COLUMN_MIN_GUTTER_BINS = 2
COLUMN_MIN_SIDE_MASS = 0.25
COLUMN_CENTRE_BAND = (0.30, 0.70)


def _column_gutter(page) -> tuple[float, float] | None:
    """The x-range of this page's column gutter, or None if it has one column."""
    try:
        words = page.extract_words()
    except Exception:
        return None
    if len(words) < COLUMN_MIN_WORDS:
        return None
    x0, x1 = page.bbox[0], page.bbox[2]
    width = x1 - x0
    if width <= 0:
        return None

    n = COLUMN_BINS
    cols = [0] * n
    for word in words:
        a = max(0, min(n - 1, int((word["x0"] - x0) / width * n)))
        b = max(0, min(n - 1, int((word["x1"] - x0) / width * n)))
        for i in range(a, b + 1):
            cols[i] += 1

    lo, hi = COLUMN_CENTRE_BAND
    best_run, best_start, run = 0, None, 0
    # The trailing sentinel closes a band that runs to the page's right edge.
    for i, count in enumerate(cols + [1]):
        if count == 0:
            run += 1
            continue
        if run and lo <= (i - run / 2) / n <= hi and run > best_run:
            best_run, best_start = run, i - run
        run = 0
    if best_start is None or best_run < COLUMN_MIN_GUTTER_BINS:
        return None

    left, right = sum(cols[:best_start]), sum(cols[best_start + best_run:])
    mass = left + right
    if left < COLUMN_MIN_SIDE_MASS * mass or right < COLUMN_MIN_SIDE_MASS * mass:
        return None
    return (x0 + best_start / n * width, x0 + (best_start + best_run) / n * width)


def _render_pipe_table(rows: list[list[str]]) -> str:
    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(_escape_pipe(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(_escape_pipe(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


def _render_page(page) -> str:
    tables = page.find_tables(TABLE_SETTINGS)

    kept = []  # (table, rows) that pass detection
    for t in tables:
        # find_tables() does not propagate text settings to extract(); without
        # TEXT_SETTINGS here, cell text silently falls back to the 3pt default
        # and re-glues words inside cells.
        rows = [[_cell_text(c) for c in row] for row in _extract_rows(page, t)]
        rows = [r for r in rows if any(r)]
        if is_real_table(rows) and not _is_diagram_debris(page, t):
            kept.append((t, rows))

    # Containment backstop: if a kept grid contains another kept grid, the outer
    # one is a frame that also passed rowfill -- drop it, its child is the table.
    def _contains(outer, inner) -> bool:
        ox0, ot, ox1, ob = outer.bbox
        ix0, it, ix1, ib = inner.bbox
        if (ox1 - ox0) * (ob - ot) <= (ix1 - ix0) * (ib - it):
            return False
        return ox0 - 2 <= ix0 and ot - 2 <= it and ox1 + 2 >= ix1 and ob + 2 >= ib

    kept = [(t, rows) for t, rows in kept
            if not any(o is not t and _contains(t, o) for o, _ in kept)]

    # Prose-exclusion boxes come from KEPT grids only. Dropped grids' text is
    # not subtracted, so it flows back through extract_text_lines as ordinary
    # prose. Cell bboxes, not the table's hull bbox: Table.extract only reads
    # chars inside cell bboxes, so text sitting in a hull gap (two grids
    # sharing a corner stretch the hull across both) belongs to no cell and
    # would otherwise vanish from the output entirely.
    boxes = [c for t, _ in kept for row in t.rows for c in row.cells if c]

    def outside_tables(obj) -> bool:
        # Centre, not full containment: an object straddling a ruling line still
        # resolves to exactly one side.
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes)

    gutter = _column_gutter(page)
    # A grid spanning both columns must never be torn in half, and it belongs
    # with the prose around it -- so one such grid discards the verdict for the
    # whole page rather than being placed into one column or the other.
    if gutter and any(t.bbox[0] < gutter[0] and t.bbox[2] > gutter[1] for t, _ in kept):
        gutter = None
    mid = (gutter[0] + gutter[1]) / 2 if gutter else 0.0

    def column_of(x0: float, x1: float) -> int:
        # Every block gets a column index, so (column, top) is a total order:
        # left column top-to-bottom, then right. Without a gutter every block
        # scores 0 and the key degenerates to today's sort by vertical
        # position, which is what keeps single-column pages byte-identical.
        return 1 if gutter and (x0 + x1) / 2 >= mid else 0

    blocks: list[tuple[int, float, bool, str]] = [
        (column_of(t.bbox[0], t.bbox[2]), t.bbox[1], True, _render_pipe_table(rows))
        for t, rows in kept
    ]

    # Prose is re-extracted per column, not merely re-sorted. extract_text_lines
    # groups by vertical position across the full page width, so a line that
    # spans the gutter is already fused into one string by the time it is
    # returned -- reordering the results cannot separate it again. Filtering the
    # page to one column first means the fused line never forms.
    if gutter:
        sources = [
            page.filter(lambda o: outside_tables(o) and (o["x0"] + o["x1"]) / 2 < mid),
            page.filter(lambda o: outside_tables(o) and (o["x0"] + o["x1"]) / 2 >= mid),
        ]
    else:
        sources = [page.filter(outside_tables)]
    for column, source in enumerate(sources):
        for line in source.extract_text_lines(**TEXT_SETTINGS):
            if line["text"].strip():
                blocks.append((column, line["top"], False, line["text"]))
    blocks.sort(key=lambda block: block[:2])

    parts: list[str] = []
    buffer: list[str] = []
    column = 0
    for block_column, _, is_grid, text in blocks:
        # A grid needs a blank line either side or markdown won't parse it, and
        # the two columns are separate runs of text rather than one paragraph.
        if is_grid or block_column != column:
            if buffer:
                parts.append("\n".join(buffer))
                buffer = []
        column = block_column
        if is_grid:
            parts.append(text)
        else:
            buffer.append(text)
    if buffer:
        parts.append("\n".join(buffer))
    return "\n\n".join(parts)


def pdf_to_markdown(source: str | Path | bytes) -> str:
    """Render a whole PDF to markdown.

    Accepts a path or the raw bytes. Bytes matter for pipeline callers, whose
    documents arrive from object storage rather than a local disk.
    """
    fp = BytesIO(source) if isinstance(source, bytes) else source
    pages = []
    with pdfplumber.open(fp) as pdf:
        for page in pdf.pages:
            pages.append(_render_page(page))
            # pdfplumber caches every char of every page; uploads run to 200MB
            # and the container has no memory limit. (With a bytes source the
            # document itself is already resident -- this still frees the much
            # larger per-char objects.)
            page.flush_cache()
    return "\n\n".join(p for p in pages if p).strip()
