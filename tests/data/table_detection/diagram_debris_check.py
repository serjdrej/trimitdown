"""Does a graphics-discard signal separate D-class (diagram debris) from real
tables on the labeled set, WITHOUT killing T? Measure before adding to the plan.

Candidate signals per labeled grid:
  - curves:   count of pdfplumber `curves` (bezier/graphics, not axis-aligned rects/lines)
              whose midpoint falls in the grid bbox
  - images:   any image bbox overlapping the grid
  - rot:      fraction of chars in the grid with upright=False (rotated text)
  - ncells:   Nurminen's min-4-cells
Only interested in signals that fire on D and NOT on T.
"""
import json, sys
from pathlib import Path

from _corpus import REPO_ROOT, corpus_dir
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import pdfplumber
from trimitdown_pdf import TABLE_SETTINGS, TEXT_SETTINGS, _cell_text
from labels import LABELS

DL = corpus_dir()
ART = Path(__file__).resolve().parent


def _row_is_filled(r): return sum(1 for c in r if c.strip()) >= 2
def is_real_table(rows):
    if len(rows) < 2 or len(rows[0]) < 2: return False
    rwc = [r for r in rows if any(c.strip() for c in r)]
    if not rwc: return False
    f = sum(1 for r in rwc if _row_is_filled(r)); return f >= 2 and f / len(rwc) >= 0.5


def inbox(x, y, b): return b[0] <= x <= b[2] and b[1] <= y <= b[3]


def features(page, t):
    b = t.bbox
    curves = 0
    for c in page.curves:
        cx = (c["x0"] + c["x1"]) / 2; cy = (c["top"] + c["bottom"]) / 2
        if inbox(cx, cy, b):
            curves += 1
    images = 0
    for im in page.images:
        ix = (im["x0"] + im["x1"]) / 2; iy = (im["top"] + im["bottom"]) / 2
        if inbox(ix, iy, b):
            images += 1
    chars = [c for c in page.chars if inbox((c["x0"]+c["x1"])/2, (c["top"]+c["bottom"])/2, b)]
    rot = sum(1 for c in chars if not c.get("upright", True)) / max(1, len(chars))
    ncells = sum(len(r.cells) for r in t.rows)
    return {"curves": curves, "images": images, "rot": round(rot, 2), "ncells": ncells}


recs = [json.loads(l) for l in (ART / "labelset.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
by_file = {}
for r in recs:
    by_file.setdefault(r["file"], []).append(r)

rows_by_label = {"T": [], "F": [], "D": []}
for fname, grids in by_file.items():
    hits = list(DL.rglob(fname))
    if not hits: continue
    with pdfplumber.open(hits[0]) as pdf:
        for g in grids:
            lbl = LABELS.get(g["gid"])
            if lbl not in ("T", "F", "D"): continue
            page = pdf.pages[g["page"]]
            for t in page.find_tables(TABLE_SETTINGS):
                if abs(t.bbox[0]-g["bbox"][0]) < 1 and abs(t.bbox[1]-g["bbox"][1]) < 1:
                    rows = [[_cell_text(c) for c in r] for r in t.extract(**TEXT_SETTINGS)]
                    rows = [r for r in rows if any(r)]
                    kept = is_real_table(rows)
                    feats = features(page, t)
                    rows_by_label[lbl].append((g["gid"], kept, feats))
                    break
            page.flush_cache()

# Focus: the grids rowfill currently KEEPS (kept=True). Among those, does any signal
# separate D (should drop) from T (must keep)?
print("Grids rowfill currently KEEPS, by true label:")
for lbl in ("T", "F", "D"):
    kept = [(g, f) for g, k, f in rows_by_label[lbl] if k]
    print(f"\n  {lbl}: {len(kept)} kept")
    for g, f in kept:
        print(f"    g{g}: curves={f['curves']:3} images={f['images']} rot={f['rot']} ncells={f['ncells']}")

# Candidate rule sweeps: for each, how many kept-D dropped vs kept-T dropped?
print("\n=== candidate discard rules (applied only to rowfill-kept grids) ===")
keptT = [f for g, k, f in rows_by_label["T"] if k]
keptD = [f for g, k, f in rows_by_label["D"] if k]
keptF = [f for g, k, f in rows_by_label["F"] if k]
def sweep(name, pred):
    dD = sum(1 for f in keptD if pred(f)); dT = sum(1 for f in keptT if pred(f)); dF = sum(1 for f in keptF if pred(f))
    print(f"  {name:32} drops D={dD}/{len(keptD)}  T={dT}/{len(keptT)}  F={dF}/{len(keptF)}")
for thr in (1, 3, 5, 10):
    sweep(f"curves >= {thr}", lambda f, t=thr: f["curves"] >= t)
sweep("images >= 1", lambda f: f["images"] >= 1)
sweep("rot > 0", lambda f: f["rot"] > 0)
sweep("ncells < 4", lambda f: f["ncells"] < 4)
for thr in (5, 10, 20):
    sweep(f"curves>={thr} AND ncells<8", lambda f, t=thr: f["curves"] >= t and f["ncells"] < 8)
