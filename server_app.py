import re
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from markitdown import MarkItDown

if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
    exe_path = Path(sys.executable).resolve()
    if sys.platform == "darwin" and ".app/Contents/MacOS" in str(exe_path):
        APP_DIR = exe_path.parents[3]  # folder containing the .app bundle
    else:
        APP_DIR = exe_path.parent
else:
    BASE_DIR = Path(__file__).parent
    APP_DIR = BASE_DIR

ARCHIVE_DIR = APP_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
md = MarkItDown()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/")
def index():
    return FileResponse(str(BASE_DIR / "static" / "index.html"))


@app.get("/manifest.json")
def manifest():
    return FileResponse(str(BASE_DIR / "static" / "manifest.json"), media_type="application/manifest+json")


@app.get("/sw.js")
def sw():
    return FileResponse(str(BASE_DIR / "static" / "sw.js"), media_type="application/javascript")


@app.get("/api/mode")
def mode():
    return {"mode": "local"}


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
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Не удалось сконвертировать файл: {e}")
    Path(tmp_path).unlink(missing_ok=True)

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
def download(filename: str):
    # application/octet-stream, not text/markdown: pywebview's cocoa backend only shows
    # the native save dialog when WKWebView can't render the response's MIME type inline
    # (canShowMIMEType()) — it ignores Content-Disposition. text/markdown is renderable as
    # plain text, so the file opened in-window instead of downloading.
    return FileResponse(safe_path(filename), filename=filename, media_type="application/octet-stream")


@app.delete("/api/archive/{filename}")
def delete(filename: str):
    safe_path(filename).unlink()
    return {"ok": True}
