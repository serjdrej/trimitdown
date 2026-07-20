# trimitdown-pdf

**The validation stage pdfplumber doesn't have.**

`page.find_tables()` answers *"where are the ruled cells?"* — it never answers
*"is this actually a table?"*. Any page frame crossed by a rule comes back as a
grid, and your pipeline renders a letterhead as a 12-column table.

This package is the missing predicate. It is not another PDF converter.

```bash
pip install trimitdown-pdf
```

## Drop it into your existing pdfplumber pipeline

If you already have a pipeline, this is the part you want. Extract rows exactly
as you do now, then ask whether the grid is real before you keep it:

```python
import pdfplumber
from trimitdown_pdf import is_real_table, TABLE_SETTINGS, TEXT_SETTINGS

with pdfplumber.open("report.pdf") as pdf:
    for page in pdf.pages:
        for table in page.find_tables(TABLE_SETTINGS):
            rows = [
                [(cell or "").replace("\n", " ").strip() for cell in row]
                for row in table.extract(**TEXT_SETTINGS)
            ]
            rows = [r for r in rows if any(r)]

            if not is_real_table(rows):
                continue  # page frame or layout box — skip it

            handle(rows)  # your existing code
```

`TABLE_SETTINGS` and `TEXT_SETTINGS` ship with the predicate because
`is_real_table` is only meaningful on rows extracted the same way it was
calibrated. `TEXT_SETTINGS` in particular is load-bearing: when
`x_tolerance_ratio` is set, pdfplumber ignores `x_tolerance` entirely, so any
call site that omits it silently reverts to the 3pt default and glues words
back together.

### What the predicate does

Nurminen's detection criterion (from tabula-java's
`NurminenDetectionAlgorithm`) applied to pdfplumber's cells: a table needs at
least two rows in which at least two columns hold content, and those rows must
be the majority of rows that have any content at all.

Measured against a 74-grid hand-labeled set: keeps 44/45 real tables, drops
13/14 layout frames. Geometric signals (cell length, coverage, empty fraction)
were tried and rejected — they destroy 29–49% of real tables.

## Or take the whole renderer

If you don't have a pipeline and just want markdown out, `pdf_to_markdown`
wraps the same detection with diagram-debris filtering, nested-frame
containment, and prose/table interleaving in document order:

```python
from trimitdown_pdf import pdf_to_markdown

print(pdf_to_markdown("report.pdf"))
```

## Limitations — read these first

- **Ruled grids only.** The engine runs with `vertical_strategy: "lines"`.
  Borderless and whitespace-aligned tables are not detected *at all* — not
  poorly, not at all. If your documents are borderless, this package does
  nothing for you.
- **No OCR.** Scanned pages and image-only PDFs produce no output. There is no
  fallback.
- **No layout model.** Multi-column page flow, reading order across columns,
  headers/footers and figure captions are out of scope.

If you need borderless tables, OCR, or full document layout, use
[marker](https://github.com/datalab-to/marker) or
[Docling](https://github.com/docling-project/docling). This package solves one
narrow problem those tools don't expose as a reusable predicate.

## Stability

**The API is unstable until 1.0.** `0.x` means names and signatures can change
in any release. Pin an exact version if you depend on it.

## API

| Name | Purpose |
| --- | --- |
| `is_real_table(rows) -> bool` | The detection predicate. |
| `pdf_to_markdown(path) -> str` | Whole-document convenience renderer. |
| `TABLE_SETTINGS` | `find_tables()` settings the predicate assumes. |
| `TEXT_SETTINGS` | `extract()` settings the predicate assumes. |
| `X_TOLERANCE_RATIO` | The tolerance ratio behind `TEXT_SETTINGS`. |

## More

- Design notes, measurements and reproduction steps:
  [`docs/pdf-engine.md`](https://github.com/serjdrej/trimitdown/blob/main/docs/pdf-engine.md)
- The application this was extracted from:
  [TrimItDown](https://github.com/serjdrej/trimitdown)

MIT licensed.
