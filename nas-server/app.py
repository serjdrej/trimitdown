import os
import re
import tempfile
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from markitdown import MarkItDown

ARCHIVE_DIR = Path("/app/archive")
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
md = MarkItDown()
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/manifest.json")
def manifest():
    return FileResponse("static/manifest.json", media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse("static/sw.js", media_type="application/javascript")


@app.get("/cert")
def get_cert():
    cert_path = Path("/certs/cert.pem")
    if not cert_path.exists():
        raise HTTPException(404, "cert not found")
    return FileResponse(cert_path, media_type="application/x-x509-ca-cert", filename="markitdown-nas.cer")


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-. ]", "_", stem, flags=re.UNICODE).strip()
    return stem or "file"


def unique_target(stem: str) -> Path:
    target = ARCHIVE_DIR / f"{stem}.md"
    if not target.exists():
        return target
    i = 2
    while True:
        candidate = ARCHIVE_DIR / f"{stem} ({i}).md"
        if not candidate.exists():
            return candidate
        i += 1


def safe_path(filename: str) -> Path:
    path = (ARCHIVE_DIR / filename).resolve()
    if ARCHIVE_DIR.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return path


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix
    data = await file.read()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        result = md.convert(tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=422, detail=f"Не удалось сконвертировать файл: {e}")
    os.unlink(tmp_path)

    text = result.text_content
    target = unique_target(safe_stem(file.filename))
    target.write_text(text, encoding="utf-8")

    return JSONResponse({"filename": target.name, "content": text})


@app.get("/api/archive")
def list_archive(q: str = ""):
    items = []
    for p in sorted(ARCHIVE_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if q and q.lower() not in p.name.lower():
            continue
        st = p.stat()
        items.append({
            "filename": p.name,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
        })
    return items


@app.get("/api/archive/{filename}")
def download(filename: str, raw: int = 0):
    # raw=1 (sent only by pywebview desktop clients, see app.js): those embedded webviews
    # decide render-vs-download by whether they can display the MIME type inline, ignoring
    # Content-Disposition, so they need application/octet-stream to force a download.
    # Regular browsers get text/markdown back — octet-stream has no type info, and iOS Safari
    # falls back to sniffing the raw bytes for a preview, sometimes misdetecting them as HTML.
    media_type = "application/octet-stream" if raw else "text/markdown"
    return FileResponse(safe_path(filename), filename=filename, media_type=media_type)


@app.delete("/api/archive/{filename}")
def delete(filename: str):
    safe_path(filename).unlink()
    return {"ok": True}
