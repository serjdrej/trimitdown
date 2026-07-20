# Table-detection tuning corpus

Fixtures and one-off measurement scripts behind the PDF engine's table-detection stage
(`core/pdf_extract.py`). They exist so that every threshold in the engine is a *measured*
value, not a guess:

- `labelset.jsonl` / `labelset.txt` — hand-labeled table candidates from a corpus of real
  PDFs: extracted grids marked as genuine tables or false positives. Used by
  `tests/test_table_detection_labeled.py` as an acceptance gate — changes to the detection
  rules must keep this set green.
- `rfsweep.py` / `rfsweep.jsonl` — parameter sweep for the row-fill vote thresholds.
- `reflowbound.py` — measurement of the word-gap threshold (glue vs over-split trade-off).
- `diagram_debris_check.py`, `partial_grid_and_tokens.py`, `rowfill_anchor_probe.py` — probes for
  specific failure classes (diagram debris, partial grids) on individual corpus documents.

The scripts are kept for reproducibility; they are not part of the test suite and may
require the original corpus PDFs, which are not committed.
