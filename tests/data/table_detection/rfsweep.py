"""Corpus sweep: shipped vs sel_ct_120 vs sel_rowfill, with two-direction parity.

New metric (the gap the brief names): numeric-token parity vs a page-text
baseline. excess = duplicated numbers (nested grids, cell-join + table double
emission); deficit = lost numbers (subtracted but unrendered content).
Both directions, corpus-wide, no labels needed.
"""
import json, re, sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, r"REPO_ROOT")
sys.stdout.reconfigure(encoding="utf-8")

import pdfplumber
import tiktoken
from core.pdf_extract import TABLE_SETTINGS, TEXT_SETTINGS, _cell_text, _escape_pipe

ENC = tiktoken.get_encoding("cl100k_base")
GLUED = re.compile(r"[A-Za-zА-Яа-яЁё]{26,}")
NUM = re.compile(r"\d+(?:[.,]\d+)*")
EPS = 2.0

def numtokens(text):
    return Counter(m for m in NUM.findall(text) if len(m) >= 2)

def contains(a, b):
    ax0, at, ax1, ab = a.bbox
    bx0, bt, bx1, bb = b.bbox
    if (ax1 - ax0) * (ab - at) <= (bx1 - bx0) * (bb - bt):
        return False
    return ax0 - EPS <= bx0 and at - EPS <= bt and ax1 + EPS >= bx1 and ab + EPS >= bb

def clean_rows(t):
    rows = [[_cell_text(c) for c in row] for row in t.extract(**TEXT_SETTINGS)]
    return [r for r in rows if any(r)]

def rowfill_keep(t, rows_raw):
    nfilled = nrows_ne = 0
    for row in rows_raw:
        ne = sum(1 for c in row if (c or "").strip())
        nrows_ne += 1 if ne else 0
        nfilled += 1 if ne >= 2 else 0
    return nfilled >= 2 and nfilled / nrows_ne >= 0.5

def assemble(blocks):
    blocks.sort(key=lambda b: b[0])
    parts, buf = [], []
    for _, is_grid, text in blocks:
        if is_grid:
            if buf:
                parts.append("\n".join(buf)); buf = []
            parts.append(text)
        else:
            buf.append(text)
    if buf:
        parts.append("\n".join(buf))
    return "\n\n".join(parts)

def render_pipe(rows):
    head, body = rows[0], rows[1:]
    out = ["| " + " | ".join(_escape_pipe(c) for c in head) + " |",
           "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(_escape_pipe(c) for c in r) + " |" for r in body]
    return "\n".join(out)

def prose_lines(page, boxes):
    def outside(obj):
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(x0 <= cx <= x1 and tp <= cy <= bt for x0, tp, x1, bt in boxes)
    return [(ln["top"], False, ln["text"]) for ln in
            page.filter(outside).extract_text_lines(**TEXT_SETTINGS) if ln["text"].strip()]

# --- shipped baseline: verbatim copy of pre-Task-2 core.pdf_extract._render_table
# and the _render_page render loop (git show cae89c3:core/pdf_extract.py), kept
# local so the baseline the sweep compares against does not depend on the code
# the sweep is grading (Task 2 deleted _render_table from core.pdf_extract).

def _shipped_render_table(table):
    rows = [[_cell_text(cell) for cell in row] for row in table.extract(**TEXT_SETTINGS)]
    rows = [row for row in rows if any(row)]
    if not rows:
        return None, False
    if len(rows) == 1:
        return " ".join(cell for cell in rows[0] if cell), False
    if len(rows[0]) == 1:
        return "\n".join(row[0] for row in rows if row[0]), False
    header, body = rows[0], rows[1:]
    lines = [
        "| " + " | ".join(_escape_pipe(c) for c in header) + " |",
        "| " + " | ".join("---" for _ in header) + " |",
    ]
    lines += ["| " + " | ".join(_escape_pipe(c) for c in row) + " |" for row in body]
    return "\n".join(lines), True


def _shipped_render_page(page, tables):
    boxes = [c for t in tables for row in t.rows for c in row.cells if c]

    def outside_tables(obj) -> bool:
        cx = (obj["x0"] + obj["x1"]) / 2
        cy = (obj["top"] + obj["bottom"]) / 2
        return not any(
            x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in boxes
        )

    blocks = []
    for table in tables:
        markdown, is_grid = _shipped_render_table(table)
        if markdown:
            blocks.append((table.bbox[1], is_grid, markdown))
    for line in page.filter(outside_tables).extract_text_lines(**TEXT_SETTINGS):
        if line["text"].strip():
            blocks.append((line["top"], False, line["text"]))
    blocks.sort(key=lambda block: block[0])

    parts = []
    buffer = []
    for _, is_grid, text in blocks:
        if is_grid:
            if buffer:
                parts.append("\n".join(buffer))
                buffer = []
            parts.append(text)
        else:
            buffer.append(text)
    if buffer:
        parts.append("\n".join(buffer))
    return "\n\n".join(parts)


def render_shipped(page, tables):
    return _shipped_render_page(page, tables)

def render_sel(page, tables, mode):
    kept = []
    for t in tables:
        rows = clean_rows(t)
        if len(rows) < 2 or len(rows[0]) < 2:
            continue
        if mode == "ct120":
            if any(o is not t and contains(t, o) for o in tables):
                continue
            if max(len(c) for r in rows for c in r) > 120:
                continue
        else:  # rowfill
            if not rowfill_keep(t, t.extract(**TEXT_SETTINGS)):
                continue
        kept.append((t, rows))
    # containment backstop among kept (rowfill): outer loses
    if mode == "rowfill":
        kept = [(t, r) for t, r in kept
                if not any(o is not t and contains(t, o) for o, _ in kept)]
    boxes = [c for t, _ in kept for row in t.rows for c in row.cells if c]
    blocks = [(t.bbox[1], True, render_pipe(rows)) for t, rows in kept]
    blocks += prose_lines(page, boxes)
    return assemble(blocks), len(kept)

def metrics(text, base_nums):
    out = numtokens(text)
    exc = sum((out - base_nums).values())
    defc = sum((base_nums - out).values())
    lines = text.splitlines()
    return {"glued": len(GLUED.findall(text)), "blob": sum(1 for l in lines if len(l) > 300),
            "paracell": sum(1 for l in lines if l.startswith("|")
                            for c in l.split("|") if len(c) > 300),
            "num_exc": exc, "num_def": defc, "tokens": len(ENC.encode(text))}

SP = Path(__file__).parent
files = sorted(p for p in Path(r"PATH_REMOVED\Downloads").rglob("*.pdf")
               if p.stat().st_size < 10 * 1024 * 1024)
print(f"{len(files)} files", flush=True)

with (SP / "rfsweep.jsonl").open("w", encoding="utf-8") as fh:
    for i, p in enumerate(files):
        rec = {"file": p.name}
        try:
            texts = {"shipped": [], "ct120": [], "rowfill": []}
            base = []
            nkept = {"ct120": 0, "rowfill": 0}
            ngrids = 0
            with pdfplumber.open(p) as pdf:
                for page in pdf.pages:
                    tables = page.find_tables(TABLE_SETTINGS)
                    ngrids += len(tables)
                    base.append(page.extract_text(**TEXT_SETTINGS) or "")
                    if tables:
                        texts["shipped"].append(render_shipped(page, tables))
                        for mode in ("ct120", "rowfill"):
                            txt, k = render_sel(page, tables, mode)
                            texts[mode].append(txt)
                            nkept[mode] += k
                    else:
                        t = "\n".join(ln["text"] for ln in
                                      page.extract_text_lines(**TEXT_SETTINGS)
                                      if ln["text"].strip())
                        for k in texts:
                            texts[k].append(t)
                    page.flush_cache()
            bn = numtokens("\n\n".join(base))
            rec["ngrids"] = ngrids
            rec["nkept"] = nkept
            for k, v in texts.items():
                rec[k] = metrics("\n\n".join(x for x in v if x).strip(), bn)
        except Exception as e:
            rec["err"] = f"{type(e).__name__}: {e}"[:150]
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if i % 25 == 0:
            print(f"{i}/{len(files)}", flush=True); fh.flush()
print("DONE", flush=True)
