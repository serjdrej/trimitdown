"""Evaluate keep/drop rules against the 79 hand-labeled grids.

Recomputes per-grid row-fill features from the PDFs, then scores each rule
both directions: kept-T (good), dropped-T (destroyed table), kept-F/D (frame
or debris rendered as table).
"""
import json, sys, collections
from pathlib import Path
sys.path.insert(0, r"REPO_ROOT")
sys.stdout.reconfigure(encoding="utf-8")
import pdfplumber
from trimitdown_pdf import TABLE_SETTINGS, TEXT_SETTINGS
from labels import LABELS

SP = Path(__file__).parent
grids = [json.loads(l) for l in (SP / "labelset.jsonl").open(encoding="utf-8")]
paths = {p.name: p for p in Path(r"PATH_REMOVED\Downloads").rglob("*.pdf")
         if p.stat().st_size < 10 * 1024 * 1024}

byfile = collections.defaultdict(list)
for g in grids:
    byfile[g["file"]].append(g)

feats = {}
for fname, gs in byfile.items():
    p = paths.get(fname)
    if not p:
        continue
    with pdfplumber.open(p) as pdf:
        for pno in sorted({g["page"] for g in gs}):
            page = pdf.pages[pno]
            tables = page.find_tables(TABLE_SETTINGS)
            for g in [x for x in gs if x["page"] == pno]:
                if g["idx"] >= len(tables):
                    continue
                t = tables[g["idx"]]
                rows = t.extract(**TEXT_SETTINGS)
                nrows_ne = 0; nfilled = 0
                for row in rows:
                    ne = sum(1 for c in row if (c or "").strip())
                    if ne:
                        nrows_ne += 1
                    if ne >= 2:
                        nfilled += 1
                rowfill = nfilled / nrows_ne if nrows_ne else 0.0
                feats[g["gid"]] = dict(g, nfilled=nfilled, nrows_ne=nrows_ne,
                                       rowfill=round(rowfill, 2))
            page.flush_cache()

RULES = {
    "shipped(keep all)":      lambda f: True,
    "maxlen<=120":            lambda f: f["maxlen"] <= 120,
    "maxlen<=300":            lambda f: f["maxlen"] <= 300,
    "mlfrac<0.5":             lambda f: f["mlfrac"] < 0.5,
    "rowfill>=0.5 & nf>=2":   lambda f: f["nfilled"] >= 2 and f["rowfill"] >= 0.5,
    "rowfill>=0.6 & nf>=3":   lambda f: f["nfilled"] >= 3 and f["rowfill"] >= 0.6,
    "rf>=0.5&nf>=2 & ml<=800":lambda f: f["nfilled"] >= 2 and f["rowfill"] >= 0.5 and f["maxlen"] <= 800,
}

print(f"{len(feats)} grids with features; labels T/F/D/A:",
      collections.Counter(LABELS[g] for g in feats))
print()
hdr = f"{'rule':26} | keptT dropT | keptF keptD | dropF dropD"
print(hdr); print("-" * len(hdr))
for name, rule in RULES.items():
    c = collections.Counter()
    for gid, f in feats.items():
        lab = LABELS[gid]
        if lab == "A":
            continue
        c[("keep" if rule(f) else "drop") + lab] += 1
    print(f"{name:26} | {c['keepT']:5} {c['dropT']:5} | {c['keepF']:5} {c['keepD']:5} | {c['dropF']:5} {c['dropD']:5}")

print("\nDetail: destroyed tables (dropT) and kept frames per rule:")
for name, rule in RULES.items():
    dropped = [g for g, f in feats.items() if LABELS[g] == "T" and not rule(f)]
    keptF = [g for g, f in feats.items() if LABELS[g] in "FD" and rule(f)]
    print(f"  {name:26} dropT={dropped} keptFD={keptF}")

print("\nPer-grid features:")
for gid in sorted(feats):
    f = feats[gid]
    print(f"  G{gid:<3} {LABELS[gid]} {f['file'][:34]:34} {f['nrows']}x{f['ncols']:<3}"
          f" maxlen={f['maxlen']:<5} mlfrac={f['mlfrac']:<5} rowfill={f['rowfill']:<5} nf={f['nfilled']}")
