# trimitdown-pdf

*Читать по-русски: [README.ru.md](https://github.com/serjdrej/trimitdown/blob/main/packages/trimitdown-pdf/README.ru.md)*

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

## Measured against markitdown

`scripts/measure_corpus.py` in the repository ran both engines over two
independent collections — 891 real-world PDFs, about 600 MB — on one machine at
one pdfplumber version (2026-07-24). Six of them are broken at the source,
encoding almost no word spacing, and are reported separately in
[`docs/pdf-engine.md`](https://github.com/serjdrej/trimitdown/blob/main/docs/pdf-engine.md)
so that a handful of pathological files cannot carry the result. The headline is
the other 885, 226 of which have no ruled grid anywhere:

| | markitdown | trimitdown-pdf |
| --- | --- | --- |
| table rows on grid-less documents | 5624 | **2** |
| glued word runs | 107 | **53** |
| documents containing glue | 24 (3%) | **18 (2%)** |
| digits invented vs page text | 0 | 0 |
| digits lost vs page text | 0 | 0 |
| conversion failures | 0 | 0 |
| output tokens | 5 528 360 | **5 011 180** (−9.4%) |

The invented-table result is the one that holds: it reproduces on each
collection separately (1497→2 and 4127→0), no document scores worse than
markitdown, and the lower token count is mostly those rows never being invented.

**Fewer tokens, and not by dropping content.** Both engines were scored against
each page's own `extract_text()`: neither invented a digit and neither lost one,
across all 885 documents. That check covers digits only — it does not prove
word-level completeness — but it rules out the failure mode where a converter
looks efficient because it quietly discards what it could not handle.

Where this engine *costs* tokens it says so. On 309 of the 885 documents the
output is larger, by a median of 32 tokens; eighteen exceed 1000. Those are the
table-dense documents, and the excess is markdown table syntax — pipes and
separator rows are what it costs to keep a structure that flat text loses.

Glue is the smaller win. The engines tie on 870 of the 885 documents; this one
is better on 11 and *loses* on four, the worst by 17 runs, on forms that encode
spacing with real space characters. That is a documented defect, not a rounding
artifact.

The corpus is third-party copyrighted material and is not published. The
measurement script is — point it at your own PDFs and it prints the same table.

## Limitations — read these first

- **Ruled grids only.** The engine runs with `vertical_strategy: "lines"`.
  Borderless and whitespace-aligned tables are not detected *at all* — not
  poorly, not at all. If your documents are borderless, this package does
  nothing for you.
- **No OCR.** Scanned pages and image-only PDFs yield no text, and there is no
  fallback. Rather than emit nothing, a page with no text layer renders as one
  line naming itself:

  ```
  [trimitdown-pdf: no extractable text layer on page 12]
  ```

  This adds no information the page did not have — it costs about 55 characters
  per page and is not a substitute for OCR. Its only job is to make the gap
  greppable, so a pipeline can route those pages to OCR instead of indexing a
  hole it never noticed. The substring `no extractable text layer` is stable and
  safe to match on. The measured corpus contained 581 such pages.
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
