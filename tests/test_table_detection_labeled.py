import json
from pathlib import Path

import pdfplumber
import pytest

from conftest import corpus_file_names
from labels import LABELS  # gid -> "T"/"F"/"D"/"A"
from trimitdown_pdf import (
    TABLE_SETTINGS, TEXT_SETTINGS, _cell_text, _is_diagram_debris, is_real_table)

ART = Path(__file__).resolve().parent / "data" / "table_detection"

# Every test here measures against the real corpus.
pytestmark = pytest.mark.corpus


def _labeled_grids(root: Path):
    """Yield (gid, label, kept) for every scoreable labeled grid found on disk.

    `kept` is the FULL selection decision — rowfill AND not diagram-debris —
    because that is what the engine actually ships.

    Documents are identified by opaque id; the id -> filename mapping is local
    and gitignored, so a checkout without the corpus resolves nothing and the
    whole set skips.
    """
    names = corpus_file_names()
    recs = [json.loads(l) for l in (ART / "labelset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_file = {}
    for r in recs:
        by_file.setdefault(r["file_id"], []).append(r)
    for fid, grids in by_file.items():
        fname = names.get(fid)
        if not fname:
            continue  # no mapping on this machine
        hits = list(root.rglob(fname))
        if not hits:
            continue  # corpus file not present on this machine
        with pdfplumber.open(hits[0]) as pdf:
            for g in grids:
                label = LABELS.get(g["gid"])
                if label not in ("T", "F", "D"):
                    continue
                page = pdf.pages[g["page"]]
                for t in page.find_tables(TABLE_SETTINGS):
                    if abs(t.bbox[0] - g["bbox"][0]) < 1 and abs(t.bbox[1] - g["bbox"][1]) < 1:
                        rows = [[_cell_text(c) for c in row] for row in t.extract(**TEXT_SETTINGS)]
                        rows = [r for r in rows if any(r)]
                        kept = is_real_table(rows) and not _is_diagram_debris(page, t)
                        yield g["gid"], label, kept
                        break
                page.flush_cache()


# Expected scoreable counts. If a labeled file is missing from disk, or rglob
# picks a same-named wrong file (its grids won't match the stored bbox and get
# dropped), the denominator shrinks below these — which must FAIL, not silently
# pass. The whole set is skipped only if NOTHING is on disk.
#
# 2026-08-06: these counts were REDUCED from {"T": 45, "F": 14, "D": 15} (74
# grids over 42 documents) after 13 of those documents were found to be gone
# from the corpus for good. Recovering them by geometry — matching every stored
# grid bbox on its stored page across the whole archive — returned 0 of 13, so
# they were deleted rather than renamed. The reduction is a recorded loss, not
# a denominator tuned to fit the data: the surviving 29 documents were rescored
# from scratch and these are the observed totals.
#
# This set is REGRESSION EVIDENCE ONLY and must never serve as an acceptance
# gate. It calibrated is_real_table and _is_diagram_debris, so it cannot judge
# them. An independent holdout is tracked separately.
EXPECTED = {"T": 31, "F": 8, "D": 14}


@pytest.fixture(scope="module")
def scored(corpus):
    rows = list(_labeled_grids(corpus))
    if not rows:
        pytest.skip(
            "no labeled document resolved under TRIMITDOWN_CORPUS. This gate scores the "
            "specific documents behind labelset.jsonl and needs both that corpus and "
            "tests/data/table_detection/labelset-files.json. To exercise the engine on "
            "your own PDFs instead, run the label-free sweeps: "
            "tests/data/table_detection/rfsweep.py and reflowbound.py "
            "(see docs/pdf-engine.md).")
    return rows


def _by_label(scored, lbl):
    got = [(gid, kept) for gid, l, kept in scored if l == lbl]
    # Full-set guard: every expected grid must have been re-extracted, or the
    # measurement is being taken on a partial set and its numbers are meaningless.
    assert len(got) == EXPECTED[lbl], (
        f"{lbl}: found {len(got)} of {EXPECTED[lbl]} labeled grids.\n"
        f"This gate scores the specific documents behind labelset.jsonl, so it is NOT "
        f"runnable on an arbitrary corpus. Failing rather than skipping is deliberate: a "
        f"partial set would report numbers measured on the wrong sample.\n"
        f"To exercise the engine on your own PDFs, use the label-free sweeps instead --\n"
        f"  python tests/data/table_detection/rfsweep.py\n"
        f"  python tests/data/table_detection/reflowbound.py\n"
        f"See docs/pdf-engine.md, 'Running the sweeps on your own PDFs'.")
    return got


def test_keeps_real_tables(scored):
    real = _by_label(scored, "T")
    kept = sum(1 for _, k in real if k)
    # Measured on the surviving 29 documents (2026-08-06): 31/31. Was 44/45 on
    # the full set before 13 documents were lost. Never regress below it.
    assert kept >= 31, f"kept only {kept}/31 real tables: {[g for g, k in real if not k]}"


def test_drops_layout_frames(scored):
    frames = _by_label(scored, "F")
    kept = sum(1 for _, k in frames if k)
    # Measured on the surviving set (2026-08-06): 1/8 kept — the same single
    # drawing title block at exactly rowfill 0.5 that this bound was written for.
    assert kept <= 1, f"kept {kept}/8 frames as tables: {[g for g, k in frames if k]}"


def test_diagram_debris_mostly_dropped(scored):
    # rowfill alone kept 7/15 debris grids; the rot>=0.15 filter drops 2 of those
    # (heavy-rotation charts), leaving 5. The curves-overlap signal was measured and
    # rejected (it also killed 4 real tables), so 5 remain a measured-open problem.
    # 2026-08-06: rescored on the surviving 29 documents — still 5, now out of 14.
    debris = _by_label(scored, "D")
    kept = sum(1 for _, k in debris if k)
    assert kept <= 5, f"kept {kept}/14 debris grids as tables: {[g for g, k in debris if k]}"
