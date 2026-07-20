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

`packages/trimitdown-pdf`, roughly 120 lines. Per page:

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
copyrighted material.

Be plain about what that costs: a reader can check the **mechanism**, not the magnitude.
**None of the numbers on this page are reader-verifiable** — every one of them needs the
corpus. What does run on a bare checkout:

- `python scripts/compare_pdf_engines.py` — stock markitdown and this engine over one
  committed sample, side by side. The phantom-column defect is visible in the output.
- `pytest -m "not corpus"` — tests over PDFs built in code. For the word-gap defect this is a
  real before/after: one test asserts the glue is present at pdfplumber's default tolerance,
  another that no absolute value fixes it while the ratio does.
- the engine itself, ~120 lines in `packages/trimitdown-pdf`.

The invented-tables and dropped-tables defects are demonstrated only on that one sample
document. The fixtures assert *this* engine's behaviour; they never re-run the stock converter.

The labeled detection set in `tests/data/table_detection/` is not reader-runnable at all. It
scores real documents, so it needs the corpus: its geometry and labels are here, the documents
are not, and neither are their filenames — records identify documents by opaque id. Those
tests carry the `corpus` marker and skip unless `TRIMITDOWN_CORPUS` is set. They are a
pre-release gate for the author, not evidence anyone else can re-run.

### Running the sweeps on your own PDFs

Two of the measurement scripts need no labels and work on any collection of documents:

```bash
export TRIMITDOWN_CORPUS=/path/to/your/pdfs
python tests/data/table_detection/rfsweep.py       # numeric-token parity, both directions
python tests/data/table_detection/reflowbound.py   # token delta from reflowing prose
```

`rfsweep.py` reports, corpus-wide, how many numbers this engine duplicates and how many it
loses against a page-text baseline — the two directions that matter, measured on documents
whose failure modes nobody here has seen.

That is the most useful thing anyone can send back: a document this engine gets wrong. The
numbers above come from one collection, skewed toward Russian technical documents. Where the
engine still lies is most likely in a corpus that looks nothing like that one.

**`pytest -m corpus` is not the tool for this.** It scores the specific documents behind
`labelset.jsonl`. Point it at an unrelated collection and it skips, saying so. Point it at a
*partial* copy of the labeled set — a few matching files, or a same-named file — and it
**fails** instead: a shrunken denominator would report ratios measured on the wrong sample,
which is exactly the kind of quietly-wrong number this engine exists to avoid.

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
