# Table-detection tuning corpus

Fixtures and one-off measurement scripts behind the PDF engine's table-detection stage
(`packages/trimitdown-pdf`). They exist so that every threshold in the engine is a *measured*
value, not a guess:

- `labelset.jsonl` — hand-labeled table candidates: the geometry of extracted grids, each
  marked in `labels.py` as a genuine table, a layout frame, or diagram debris. Used by
  `tests/test_table_detection_labeled.py` as an acceptance gate — changes to the detection
  rules must keep this set green.
- `reflowbound.py` — measurement of the word-gap threshold (glue vs over-split trade-off).
- `rfsweep.py` — parameter sweep for the row-fill vote thresholds.
- `diagram_debris_check.py`, `partial_grid_and_tokens.py`, `rowfill_anchor_probe.py` — probes for
  specific failure classes (diagram debris, partial grids) on individual corpus documents.

## The corpus is not here, and neither are its filenames

The documents these were measured on are third-party copyrighted material. They are not in
this repository and will not be. Their **filenames are not here either**: `labelset.jsonl`
identifies each document by an opaque id, and the id -> filename mapping lives in
`labelset-files.json`, which is gitignored and exists only on a machine that owns the corpus.

Everything here therefore needs `TRIMITDOWN_CORPUS` pointing at the directory holding the PDFs:

```bash
export TRIMITDOWN_CORPUS=/path/to/corpus
pytest -m corpus                                   # the acceptance gate
python tests/data/table_detection/reflowbound.py   # a measurement script
```

Without it the tests skip (`corpus` marker) and the scripts exit with an explanation. The
scripts are kept for reproducibility by the author; they are not part of the test suite.

The part of the suite that runs anywhere is `tests/pdf_fixtures.py` — minimal PDFs built in
code that reproduce each measured defect. `pytest -m "not corpus"` runs on those alone and
needs nothing external.
