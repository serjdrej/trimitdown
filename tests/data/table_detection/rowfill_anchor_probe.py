"""Rowfill rule on the acceptance-anchor anchor: does it drop the page frame, keep the 8x4?"""
import sys
from _corpus import REPO_ROOT, corpus_dir
sys.path.insert(0, str(REPO_ROOT))
sys.stdout.reconfigure(encoding="utf-8")
import pdfplumber
from trimitdown_pdf import TABLE_SETTINGS, TEXT_SETTINGS

def rowfill(t):
    rows = t.extract(**TEXT_SETTINGS)
    nrows_ne = nfilled = 0
    for row in rows:
        ne = sum(1 for c in row if (c or "").strip())
        nrows_ne += 1 if ne else 0
        nfilled += 1 if ne >= 2 else 0
    return nfilled, (nfilled / nrows_ne if nrows_ne else 0.0)

from _corpus import corpus_paths

for path in corpus_paths(["b5beaa148386", "9e72d0867b56"]):
    print("=", path.rsplit("\\", 1)[1])
    with pdfplumber.open(path) as pdf:
        for pno, page in enumerate(pdf.pages):
            for i, t in enumerate(page.find_tables(TABLE_SETTINGS)):
                nf, rf = rowfill(t)
                keep = nf >= 2 and rf >= 0.5
                rows = t.extract(**TEXT_SETTINGS)
                nr, nc = len(rows), len(rows[0]) if rows else 0
                print(f"  p{pno} idx{i} {nr}x{nc} bbox={[round(v) for v in t.bbox]}"
                      f" nf={nf} rf={rf:.2f} -> {'KEEP' if keep else 'drop'}")
            page.flush_cache()
