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

Measured on the corpus (see [Corpus](#corpus)), the stock converter fails in three distinct
ways:

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
5. Blocks are ordered by vertical position — except on a page detected as two-column, where
   the prose is re-extracted per column and the whole left column is emitted before the whole
   right one (see [Reading order](#reading-order-on-two-column-pages)). Accepted grids render
   as markdown tables.

On prior art: the *idea* of a detection stage is not new — tabula-java's
`NurminenDetectionAlgorithm` defines it, and validates candidates by text-edge alignment and
graphics intersection. What appears to be absent in Python is a detection stage expressed as a
**cell-fill vote on pdfplumber's ruled grids**, with per-grid degradation back to prose. The
relative word-gap tolerance itself is *not* novel — `x_tolerance_ratio` is a stock pdfplumber
parameter and pdfminer's `word_margin` has always been relative. What is ours there is the
*measured selection* of the value, not the mechanism.

### Reading order on two-column pages

Ordering prose by vertical position alone reads a two-column page straight across the gutter,
fusing the left and right columns into single lines. Nothing in the shipped metrics can see
this: the digit rows are blind to order by construction, and a fused line loses no character.
It was measured separately, over 891 documents / 6697 pages. The gutter detector fires on
**213 pages (3.2%)** across **80 documents (9.0%)**.

Those 213 are not 213 two-column *prose* pages, and the first pass at this said they were.
Scored again against the engine's own output rather than against raw page geometry:

| | pages | fused prose lines, before | after |
|---|---|---|---|
| two-column prose — page is split | 83 | 673 | **1** |
| gutter is a wide table's own column gap — split refused | 130 | 237 | 237 |
| | **213** | **910** | **238** |

On those 130 pages a mean of **86%** of the page's words sit inside an accepted grid, and 118
of the 130 are over 50%. The "columns" there are a ruled table's own column groups, not a
prose layout, and the engine already rendered that text as grid rows rather than as fused
prose. The guard refuses to split them, which is the correct outcome for the right reason.

That also corrects the first measurement's headline. It counted geometric word-lines over the
raw page — every row of a wide table has words on both sides of the gutter, so every row
scored as fused — and reported 5702 fused lines of 11185. Against the engine's actual output
the prose-level defect was 910 lines, and 4792 of the difference was table rows that were
never fused in the first place. Same detector, same 213 pages; the number moved by 6x because
the thing being counted changed. Measure the output, not the page.

**Detection.** Word bboxes are projected onto 60 x-bins. The widest empty band whose centre
sits in the middle 40% of the page is the gutter candidate, accepted only if each side holds
at least a quarter of the word mass, on a page with at least 60 words. The 60-word floor is
what stops a sparse page's ordinary ragged whitespace from reading as a column boundary, and
the mass test is what stops a margin note or a page number from doing the same. Detection is
per page, not per document: a two-column document with a single-column first page is common.

The detector in the engine is the one that produced the table above, ported rather than
re-derived. That is deliberate: a fix tuned to a slightly different definition of
"two-column" than the measurement's would make its own before/after numbers meaningless.

**The fix is a re-extraction, not a re-sort.** `extract_text_lines` groups by vertical
position across the full page width, so a line spanning the gutter is already fused into one
string by the time it is returned — reordering the results cannot separate it again. The page
is filtered to one column first, so the fused line never forms.

**The guard.** If an accepted grid spans both columns, the page is not split at all. A table
is a single object that legitimately crosses the gutter; splitting the page around it would
tear it from the prose it belongs with. One such grid discards the verdict for the whole page
rather than being assigned to a column.

Two columns only. Three-column layouts are not handled and are not detected as anything —
they fall through to the single-column path, which is the behaviour they had before.

**Result.** Across the 80 affected documents, 42 improved, 38 are unchanged and **0
regressed**. Of the 38, 36 were never split at all — their only detected pages were
guard-blocked table pages — and the other 2 were split but had no fused line to begin with.
On 100 documents where the detector finds no gutter at all, output is byte-identical to the
pre-change engine, which is the assertion that matters most: 97% of corpus pages are single
column and none of them may move.

## Measured results

The numbers below come from running `scripts/measure_corpus.py` — the same tool the
[next section](#re-measuring-on-your-own-pdfs) hands to a reader — over two independent
collections, 891 documents in all (~600 MB) after removing the duplicates that appear in both.
A reader reproduces the *method* and the output format on their own documents, not these
magnitudes.

Six of the 891 are broken at the source — scans and exports that encode almost no word spacing,
where even the stock converter's own gluing runs into the hundreds. Those are reported
[separately](#broken-source-documents) so a single pathological file cannot carry the result.
The headline is the other 885 (226 of them with no ruled grid anywhere):

| | markitdown | TrimItDown |
|---|---|---|
| table rows on grid-less documents | **5624** | **2** |
| glued word runs | 107 | **53** |
| documents containing glue | 24 (3%) | 18 (2%) |
| digits duplicated vs page text | 0 | **0** |
| digits lost vs page text | 0 | 0 |
| output tokens | 5 528 360 | **5 001 929** |
| conversion failures | 0 | 0 |
| median seconds per document | 0.107 s | **0.098 s** |
| total runtime | 895 s | 909 s |

Read it top to bottom — the order is the honest order.

**Invented tables are the result that holds.** 5624 rows of prose reshaped into tables, on the
documents where pdfplumber finds no grid to justify a single one, against two from this engine —
and the split reproduces on each collection separately (1497→2 and 4127→0). This is what the
row-fill validation stage buys, and it is the defect with the largest token cost: the ~9% lower
token count is mostly those rows never being invented.

**Glue is a modest, honest win.** On 870 of the 885 documents the two engines tie, almost always
at zero — the medians are 0 for both. Over the whole set this engine glues about half as much
(107 vs 53). It *loses* on four documents, one of them materially: a form with real space
characters where the relative threshold still fuses 26 runs against markitdown's 9. On a
document that encodes its spaces, geometry should defer to them; here it does not yet, and that
is a real defect, not a metric artifact.

**The digit rows are a self-check, and they earned their place.** Zero in both directions is the
only result markitdown can post — it pastes a page's text through in reading order, so it *is*
approximately the baseline. The row exists for this engine, which restructures pages and can
therefore genuinely repeat or drop a digit. It did: an earlier build emitted **3138 duplicated
digits across 27 documents**, every one traced to overlapping cell rectangles being read twice
(see the nested-cell subtraction in the pipeline above). The row is what caught it, and zero is
what the fix produced. Read a clean parity row as "nothing was dropped or repeated", not as
"the numbers are right" — digit counts are blind to order, and nothing printed here covers that.

An earlier version of this document reported these two rows as evidence of nothing, calling the
metric confounded because its direction reversed between the two collections. That reading was
wrong. The metric it described counted number *tokens*, and a cell boundary landing mid-number
splits one token into two — so the reversal tracked which collection had more tables, not which
engine was more faithful. Counting digit characters instead removes the artifact, and what was
left was not noise but a real bug. The lesson is in
[Re-measuring](#re-measuring-on-your-own-pdfs); it is repeated here because the wrong conclusion
was published first.

**On speed, the median and the total disagree, so both are printed.** This engine is faster on
**533 of the 885 documents** and faster at the median (0.098 s against 0.107 s), while being
1.5% slower over the corpus as a whole. Both are true because the total is not describing a
document: **the ten slowest documents, 1.1% of the corpus, carry 40% of the runtime, and the
slowest fifty carry 72%.** A reader converting a document should read the median; someone
converting a whole archive should read the total.

The two most recent stages cost what they cost, measured by timing them directly rather than by
differencing two runs: the column detector 2.6% of conversion time, the cell-overlap scan 1.4%.
Run-to-run wall-clock on the same machine moves by a comparable amount, which is why a total
runtime lifted from a different run is not evidence about either.

### Broken-source documents

Six documents in the combined set encode almost no word spacing at the source — the
space-to-glyph ratio is near zero and no gap is wide enough to split words. On five of the six
this engine still emits zero glued runs against 52–256 from the stock converter; on the worst,
a scan, both fail but this engine is still ahead (413 glued vs 508). The conclusion the glue
numbers above describe — that the mechanism works on well-formed documents — does not rest on
these, and on the broken ones this engine is not worse, only less dramatically better.

The word-gap threshold itself was chosen by scoring **both** failure directions — gluing *and*
over-splitting — across a 136-file slice of the corpus, not by tuning until gluing disappeared:

| threshold | glued runs | files affected | over-split proxy |
|---|---|---|---|
| absolute 3 pt (pdfplumber default) | 3209 | 38 | 3929 |
| absolute 2 pt | 269 | 30 | 4207 |
| **relative 0.12 × font size** | **27** | **20** | see note |

No absolute point value ports across font sizes — 2 pt cuts gluing but over-splits more, 3 pt
does the reverse. The ratio is what holds; the residual it leaves is the broken-source floor
above, scans with no spacing to recover.

## Corpus

Two independent collections, 891 real-world PDFs in all, about 600 MB: Russian and English
technical datasheets, patents, hydraulics catalogues, bank forms, medical scans, a thesis,
slide decks, service manuals.

**The corpus is not in this repository and will not be**, because it is third-party
copyrighted material.

Be plain about what that costs: a reader can check the **mechanism**, not the magnitude.
**None of the numbers on this page are reader-verifiable** — every one of them needs the
corpus. What a reader can do instead is produce their own set of the same numbers, on their
own documents: see [Re-measuring on your own PDFs](#re-measuring-on-your-own-pdfs). What runs
on a bare checkout, with no documents of your own:

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

### Re-measuring on your own PDFs

The table above is not reproducible, but the measurement is. Point this at any directory of
PDFs and it runs both converters over all of them and prints the same rows:

```bash
python scripts/measure_corpus.py /path/to/your/pdfs
```

It needs no labels and no corpus of ours. Add `--limit 50` for a first look — that draws 50
documents at random (seeded, so it is reproducible), not the first 50 by name, which would be
one folder rather than a cross-section.

What it reports, per engine: glued word runs, documents containing glue, mojibake characters
and documents that are mostly mojibake, table rows emitted on documents where pdfplumber
finds no ruled grid at all, digits duplicated and digits lost
against a page-text baseline, failures, output tokens, and both the median seconds per document
and the total runtime — they answer different questions and on our corpus they disagree, because
a handful of very long documents carry most of the total. Totals plus medians throughout, because
on the number rows the median is usually zero and the total is usually two or three
documents — read them together or the total will mislead you.

The two digit rows are a self-check on this engine, not a head-to-head, and they are printed
that way deliberately. The baseline is pdfplumber's page text, and markitdown pastes a page's
text through in reading order — so markitdown *is* approximately the baseline. Over all 893
documents of the private corpora it scored exactly zero in both directions on every one of
them. There is no result markitdown can post here other than zero. This engine reshapes
pages, so it can genuinely lose or repeat a digit, and the row exists to catch that — it
caught 3138 duplicated digits on 27 documents, all from one bug in cell rendering.

They count digit characters rather than number tokens for a reason worth stating, because the
first version of this row did the opposite and reversed direction between the two corpora.
Tokens confuse re-tokenisation with data loss: a cell boundary landing between the `1` and the
`0` of a `10` turns one token into two, and the "two or more digits" filter then discards
both, so a document scores as having lost a number it still carries in full. One 349-page
catalogue produced 791 "numbers lost" that way and lost no digit at all. Across all 893
documents the digit deficit was zero for both engines on every single one, while the token
metric claimed 1492 losses for this engine and 1356 for markitdown — all of it layout, none
of it data. That row also reversed direction between the two corpora, which is how it was
caught: it is dominated by whichever corpus is more table-heavy, not by which engine is more
faithful.

The two mojibake rows are **diagnostic only**. cp1251 Cyrillic whose bytes are decoded as
latin-1 lands almost entirely in `U+00C0-U+00FF`, so a document that came through the wrong
codec is a dense run of accented Latin letters. Nothing in the engine repairs this, and
nothing should on the strength of this counter alone — the character count cannot by itself
tell a mis-decoded Russian document from a French one, which is why the second row counts
documents where the class exceeds 15% of the output. Real prose in any Latin-script language
stays well under that; a wholly mis-decoded document is most of it. The rows exist so that
the next full corpus run yields the frequency for free, rather than needing its own sweep.

Digit counts are blind to order, and nothing else printed here covers it. Two overlapping text
layers whose glyphs interleave — `123` and `.4XYZ` coming out as `.14X2Y3Z` — conserve every
digit and score clean on both rows. That failure is real and is in the corpus. Read a clean
parity row as "nothing was dropped or repeated", not as "the numbers are right".

**The summary it prints is counts only** — no filenames, no paths, no document text — so it
can be pasted into an issue as-is. Per-document rows, which do name files, go to a separate
local file (`--details`, gitignored by default). That split exists because this repository
once published a per-document listing that should never have left the machine.

Two further scripts measure narrower things and also need no labels:

```bash
export TRIMITDOWN_CORPUS=/path/to/your/pdfs
python tests/data/table_detection/rfsweep.py       # numeric parity across three variants
python tests/data/table_detection/reflowbound.py   # token delta from reflowing prose
```

### Sending results back

Every summary is worth having, not only the ones where this engine loses. There is an
[issue template](https://github.com/serjdrej/trimitdown/issues/new?template=measurement.yml)
for them.

Collecting only the failures would build a sample made of failures — it would show where the
engine breaks, but it could never say how often, because the runs where nothing broke were
never counted. That is the same mistake as counting table candidates without inspecting them,
which is how a page frame ended up in this project's own numbers once.

The published table comes from one collection, skewed toward Russian technical documents.
Pooled across corpora in other languages, other layouts and other scanners, the same rows
would mean something a single collection cannot make them mean. Wins and ties carry that
weight as much as losses do.

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
