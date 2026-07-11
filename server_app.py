import sys
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from config_store import APP_DIR
from core.converter import convert_and_save, delete_file, list_archive, safe_path

BASE_DIR = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).parent
ARCHIVE_DIR = APP_DIR / "archive"
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
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


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    return await convert_and_save(ARCHIVE_DIR, file)


@app.get("/api/archive")
def archive(q: str = ""):
    return list_archive(ARCHIVE_DIR, q)


@app.get("/api/archive/{filename}")
def download(filename: str):
    # application/octet-stream, not text/markdown: pywebview's cocoa backend only shows
    # the native save dialog when WKWebView can't render the response's MIME type inline
    # (canShowMIMEType()) — it ignores Content-Disposition. text/markdown is renderable as
    # plain text, so the file opened in-window instead of downloading. This local server only
    # ever talks to the bundled pywebview shell, so there's no browser client to accommodate.
    return FileResponse(safe_path(ARCHIVE_DIR, filename), filename=filename, media_type="application/octet-stream")


@app.delete("/api/archive/{filename}")
def delete(filename: str):
    delete_file(ARCHIVE_DIR, filename)
    return {"ok": True}
