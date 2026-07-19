"""Combined: finish Q1 partial-grid over all files, and record markitdown vs
rowfill token counts per file for Q2 (the product objective)."""
import json, re, sys
from pathlib import Path
sys.path.insert(0, r"REPO_ROOT")
sys.stdout.reconfigure(encoding="utf-8")
import pdfplumber, tiktoken
from markitdown import MarkItDown
from core.pdf_extract import TABLE_SETTINGS, TEXT_SETTINGS, _cell_text, _escape_pipe

ENC = tiktoken.get_encoding("cl100k_base"); md = MarkItDown()
NUM = re.compile(r"\d")

def _row_is_filled(r): return sum(1 for c in r if c.strip()) >= 2
def is_real_table(rows):
    if len(rows)<2 or len(rows[0])<2: return False
    rwc=[r for r in rows if any(c.strip() for c in r)]
    if not rwc: return False
    f=sum(1 for r in rwc if _row_is_filled(r)); return f>=2 and f/len(rwc)>=0.5
def contains(a,b):
    ax0,at,ax1,ab=a.bbox; bx0,bt,bx1,bb=b.bbox
    if (ax1-ax0)*(ab-at)<=(bx1-bx0)*(bb-bt): return False
    return ax0-2<=bx0 and at-2<=bt and ax1+2>=bx1 and ab+2>=bb
def partial(page,t):
    x0,top,x1,bottom=t.bbox; ncol=max(len(r.cells) for r in t.rows); nrow=len(t.rows)
    colw=(x1-x0)/max(1,ncol); rowh=(bottom-top)/max(1,nrow); r=b=0
    for w in page.extract_words(**TEXT_SETTINGS):
        if not NUM.search(w["text"]): continue
        wx=(w["x0"]+w["x1"])/2; wy=(w["top"]+w["bottom"])/2
        if x1+1<wx<x1+colw*1.2 and top-2<=wy<=bottom+2: r+=1
        if bottom+1<wy<bottom+rowh*1.2 and x0-2<=wx<=x1+2: b+=1
    return r>=2 or b>=2
def rowfill_render(page):
    tables=page.find_tables(TABLE_SETTINGS); kept=[]
    for t in tables:
        rows=[[_cell_text(c) for c in r] for r in t.extract(**TEXT_SETTINGS)]; rows=[r for r in rows if any(r)]
        if is_real_table(rows): kept.append((t,rows))
    kept=[(t,r) for t,r in kept if not any(o is not t and contains(t,o) for o,_ in kept)]
    boxes=[c for t,_ in kept for row in t.rows for c in row.cells if c]
    def outside(o):
        cx=(o["x0"]+o["x1"])/2; cy=(o["top"]+o["bottom"])/2
        return not any(x0<=cx<=x1 and tp<=cy<=bt for x0,tp,x1,bt in boxes)
    blocks=[(t.bbox[1],True,"\n".join(["| "+" | ".join(_escape_pipe(c) for c in rows[0])+" |","| "+" | ".join("---" for _ in rows[0])+" |"]+["| "+" | ".join(_escape_pipe(c) for c in r)+" |" for r in rows[1:]])) for t,rows in kept]
    for ln in page.filter(outside).extract_text_lines(**TEXT_SETTINGS):
        if ln["text"].strip(): blocks.append((ln["top"],False,ln["text"]))
    blocks.sort(key=lambda b:b[0]); parts=[]; buf=[]
    for _,g,tx in blocks:
        if g:
            if buf: parts.append("\n".join(buf)); buf=[]
            parts.append(tx)
        else: buf.append(tx)
    if buf: parts.append("\n".join(buf))
    return "\n\n".join(parts), len(kept), sum(1 for t,_ in kept if partial(page,t))

files=sorted(p for p in Path(r"PATH_REMOVED\Downloads").rglob("*.pdf") if p.stat().st_size<10*1024*1024)
print(f"{len(files)} files",flush=True)
out=Path(r"PATH_REMOVED\AppData\Local\Temp\claude\REPO_ROOT\SESSION_ID\scratchpad\q1q2.jsonl")
with out.open("w",encoding="utf-8") as fh:
    for i,p in enumerate(files):
        rec={"file":p.name}
        try:
            kept=part=0; pages=[]
            with pdfplumber.open(p) as pdf:
                for page in pdf.pages:
                    txt,k,pt=rowfill_render(page); pages.append(txt); kept+=k; part+=pt; page.flush_cache()
            rf_txt="\n\n".join(x for x in pages if x).strip()
            rec["kept"]=kept; rec["partial"]=part; rec["rf_tokens"]=len(ENC.encode(rf_txt))
            try: rec["mit_tokens"]=len(ENC.encode(md.convert(str(p)).text_content))
            except Exception: rec["mit_tokens"]=None
        except Exception as e:
            rec["err"]=f"{type(e).__name__}: {e}"[:120]
        fh.write(json.dumps(rec,ensure_ascii=False)+"\n")
        if i%50==0: print(f"{i}/{len(files)}",flush=True); fh.flush()
print("DONE",flush=True)
