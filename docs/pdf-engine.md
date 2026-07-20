# The PDF engine — design and measurements

Why TrimItDown does not use markitdown's stock PDF converter, what was measured, and how to
reproduce it. Non-PDF formats (DOCX/PPTX/XLSX/EPUB/HTML/Outlook) still go through
[MarkItDown](https://github.com/microsoft/markitdown) and are out of scope here.

## The objective

TrimItDown converts documents so they can be pasted into an LLM. **Fewer tokens with the
information preserved** is the objective function — not visual fidelity to the original page.
That distinction drives every trade-off below: a table rendered as a real markdown table is
worth its tokens, a table hallucinated out of prose is not.

## Constraints

These were fixed before any implementation and ruled out most of the field:

- **License:** MIT/BSD/Apache only. No AGPL (rules out PyMuPDF / pymupdf4llm), no GPL.
- **No ML runtimes.** No torch/ONNX — the desktop build is a PyInstaller single file that
  must stay downloadable, and must run fully offline.
- **Thread-safe**, to fit the existing `asyncio.to_thread` offload.

## The three defects

Measured on a corpus of ~700 real PDFs (see [Corpus](#corpus)), the stock converter fails in
three distinct ways:

1. **Glued words.** Word boundaries are decided by an *absolute* point threshold. No single
   value ports across font sizes: one corpus file needs a threshold below 2.89 pt, a
   small-print patent needs below 0.74 pt. Whatever you pick, one of them breaks.
2. **Invented tables.** Rows are emitted on pages that contain no grid at all — ordinary
   prose reformatted as a table.
3. **Dropped real tables.** Genuine ruled tables lose their structure and arrive as a run-on
   line of cell text.

## The design

`core/pdf_extract.py`, roughly 120 lines. Per page:

1. `find_tables` with both strategies set to `lines` — candidate grids from ruled lines only.
2. **The row-fill validation stage** (this is the part that does not exist upstream): a
   candidate grid is accepted only if its cells are actually filled like a table — at least
   two rows with at least two filled cells, covering at least half the non-empty rows. A page
   border, a diagram frame, or a decorative box fails this test.
3. Cell bboxes of *accepted* grids are subtracted from the prose layer. A **rejected** grid is
   not deleted — its text flows back into the prose stream, per grid. Nothing is lost.
4. Prose is extracted with a **relative** word-gap threshold (`x_tolerance_ratio=0.12`) — a
   fraction of the font size, which is what makes it hold across small and large type.
5. Blocks are ordered by vertical position; accepted grids render as markdown tables.

On prior art: the *idea* of a detection stage is not new — tabula-java's
`NurminenDetectionAlgorithm` defines it, and validates candidates by text-edge alignment and
graphics intersection. What appears to be absent in Python is a detection stage expressed as a
**cell-fill vote on pdfplumber's ruled grids**, with per-grid degradation back to prose. The
relative word-gap tolerance itself is *not* novel — `x_tolerance_ratio` is a stock pdfplumber
parameter and pdfminer's `word_margin` has always been relative. What is ours there is the
*measured selection* of the value, not the mechanism.

## Measured results

Full corpus run, stock markitdown vs the shipped engine:

| | markitdown | TrimItDown |
|---|---|---|
| glued word runs | 1153 | **27** |
| files containing glue | 31 | 20 |
| fake tables (rows emitted on grid-less pages) | **49 files / 2442 rows** | **1 file** |
| conversion failures | 0 | **0** |
| total runtime | 993 s | 976 s |

The word-gap threshold was chosen by scoring **both** failure directions — gluing *and*
over-splitting — across 136 files, rather than tuning until gluing disappeared:

| threshold | glued runs | files affected | over-split proxy |
|---|---|---|---|
| absolute 3 pt (pdfplumber default) | 3209 | 38 | 3929 |
| absolute 2 pt | 269 | 30 | 4207 |
| **relative 0.12 × font size** | **27** | **20** | see note |

The residual 20-file glue floor is not reachable by any tolerance — those are mostly scans
with roughly one glued run each, and some are likely metric false positives.

## Corpus

~700 real-world PDFs, about 1.1 GB: Russian and English technical datasheets, patents,
hydraulics catalogues, bank forms, medical scans, a thesis, slide decks, service manuals.

**The corpus is not in this repository and will not be**, because it is third-party
copyrighted material. This is the honest limitation of the numbers above: they are
reproducible by the author, not by a reader. What a reader *can* reproduce is:

- the **single-document comparison** below, on a sample file committed to this repo;
- the **labeled detection set** in `tests/data/table_detection/`, which pins the detection
  rules and runs as part of the test suite (`python -m pytest`);
- the **hand-built fixtures** in `tests/pdf_fixtures.py`, minimal PDFs that reproduce each
  measured defect — including a case proving a relative threshold does something no absolute
  value can.

## Reproducing the comparison

```bash
python scripts/compare_pdf_engines.py tests/data/sample-service-report.pdf
```

This runs both converters over the same committed file and prints both outputs. The sample is
a synthetic service report built to contain one ordinary ruled table; the stock converter
inserts a phantom empty column into it and shifts the header row, which is the defect shown in
the README.

## A note on method

This project's recurring failure mode has been confident conclusions from narrow evidence.
Several beliefs that survived review were later falsified by measurement — that the gluing
needed a different PDF library (it was a tolerance value), that an absolute tolerance was
"measured, not a guess" (it cannot port across font sizes), that the table counts looked
plausible (they had been counted, never inspected — one of them was a page frame). The
labeled set and the both-direction scoring exist specifically because of that history.
