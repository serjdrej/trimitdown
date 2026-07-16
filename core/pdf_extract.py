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


def _render_page(page) -> str:
    lines = page.extract_text_lines(x_tolerance=X_TOLERANCE)
    return "\n".join(line["text"] for line in lines if line["text"].strip())


def pdf_to_markdown(path: str | Path) -> str:
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            pages.append(_render_page(page))
            # pdfplumber caches every char of every page; uploads run to 200MB
            # and the container has no memory limit.
            page.flush_cache()
    return "\n\n".join(p for p in pages if p).strip()
