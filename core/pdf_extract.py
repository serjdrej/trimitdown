"""PDF -> markdown.

markitdown's .pdf converter has three defects measured on real documents: it
glues words together, invents tables out of prose, and drops real ruled tables.
This module replaces it. Every other format still goes through markitdown.

See docs/superpowers/specs/2026-07-16-pdf-extraction-diagnosis.md.
"""

from pathlib import Path

import pdfplumber

# Words are separated by positioning, not space characters. The measured
# inter-word gap on real documents is 2.89-2.93pt, a hair under pdfplumber's 3pt
# default; intra-word gaps are ~0.0pt, so 2 sits in a wide safe band.
X_TOLERANCE = 2
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
TEXT_SETTINGS = {"x_tolerance": X_TOLERANCE}


def _cell_text(value: str | None) -> str:
    return (value or "").replace("\n", " ").replace("|", "\\|").strip()


def _render_table(table) -> tuple[str | None, bool]:
    """Render one detected grid. Returns (markdown, is_grid).

    Single-row tables come back with is_grid=False: they render as a plain line
    and flow into the surrounding prose, because as markdown they would be a
    header row with no body.
    """
    # find_tables() does not propagate text settings to extract(); without
    # TEXT_SETTINGS here, cell text silently falls back to the 3pt default and
    # re-glues words inside cells.
    rows = [[_cell_text(cell) for cell in row] for row in table.extract(**TEXT_SETTINGS)]
    rows = [row for row in rows if any(row)]
    if not rows:
        return None, False
    if len(rows) == 1:
        return " ".join(cell for cell in rows[0] if cell), False
    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines), True


def _render_page(page) -> str:
    tables = page.find_tables(TABLE_SETTINGS)
    boxes = [table.bbox for table in tables]

    def outside_tables(obj) -> bool:
        # Centre, not full containment: an object straddling a ruling line still
        # resolves to exactly one side.
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(
            x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes
        )

    blocks: list[tuple[float, bool, str]] = []
    for table in tables:
        markdown, is_grid = _render_table(table)
        if markdown:
            blocks.append((table.bbox[1], is_grid, markdown))
    for line in page.filter(outside_tables).extract_text_lines(x_tolerance=X_TOLERANCE):
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
