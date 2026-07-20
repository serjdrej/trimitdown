"""PDF -> markdown.

markitdown's .pdf converter has three defects measured on real documents: it
glues words together, invents tables out of prose, and drops real ruled tables.
This module replaces it. Every other format still goes through markitdown.

See docs/pdf-engine.md for the design, the measurements and how to reproduce them.
"""

from pathlib import Path

import pdfplumber

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
        rows = [[_cell_text(c) for c in row] for row in t.extract(**TEXT_SETTINGS)]
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

    blocks: list[tuple[float, bool, str]] = [
        (t.bbox[1], True, _render_pipe_table(rows)) for t, rows in kept
    ]
    for line in page.filter(outside_tables).extract_text_lines(**TEXT_SETTINGS):
        if line["text"].strip():
            blocks.append((line["top"], False, line["text"]))
    blocks.sort(key=lambda block: block[0])

    parts: list[str] = []
    buffer: list[str] = []
    for _, is_grid, text in blocks:
        if is_grid:
            # A grid needs a blank line either side or markdown won't parse it.
            if buffer:
                parts.append("\n".join(buffer))
                buffer = []
            parts.append(text)
        else:
            buffer.append(text)
    if buffer:
        parts.append("\n".join(buffer))
    return "\n\n".join(parts)


def pdf_to_markdown(path: str | Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(_render_page(page))
            # pdfplumber caches every char of every page; uploads run to 200MB
            # and the container has no memory limit.
            page.flush_cache()
    return "\n\n".join(p for p in pages if p).strip()
