"""Upper bound on token savings from reflowing hard-wrapped prose lines.

Within each block (split on \n\n), if no line is a table row, join lines with
a space. Measures tiktoken delta on a deterministic 30-file sample.
"""
import sys, random
from pathlib import Path
sys.path.insert(0, r"REPO_ROOT")
sys.stdout.reconfigure(encoding="utf-8")
import tiktoken
from trimitdown_pdf import pdf_to_markdown

ENC = tiktoken.get_encoding("cl100k_base")
files = sorted(p for p in Path(r"PATH_REMOVED\Downloads").rglob("*.pdf")
               if p.stat().st_size < 10 * 1024 * 1024)
rng = random.Random(7)
sample = rng.sample(files, 30)

tot_before = tot_after = 0
for p in sample:
    try:
        md = pdf_to_markdown(p)
    except Exception:
        continue
    blocks = md.split("\n\n")
    out = []
    for b in blocks:
        if any(l.startswith("|") for l in b.splitlines()):
            out.append(b)
        else:
            out.append(" ".join(b.splitlines()))
    md2 = "\n\n".join(out)
    tot_before += len(ENC.encode(md))
    tot_after += len(ENC.encode(md2))
print(f"30-file sample: tokens {tot_before} -> {tot_after} "
      f"({100*(tot_after-tot_before)/tot_before:+.2f}%)")
