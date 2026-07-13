import json
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config_store import APP_DIR
from core.converter import convert_and_save, convert_batch, delete_file, list_archive, safe_path, zip_archive_files

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


@app.post("/api/convert-batch")
async def convert_batch_endpoint(files: list[UploadFile] = File(...)):
    from fastapi import HTTPException

    if len(files) > 10:
        raise HTTPException(400, detail="Максимум 10 файлов за раз / Maximum 10 files at a time")

    async def event_stream():
        async for event in convert_batch(ARCHIVE_DIR, files):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/archive-zip")
def download_zip(names: str):
    buffer = zip_archive_files(ARCHIVE_DIR, names.split(","))
    filename = f"trim_{datetime.now():%Y%m%d_%H%M%S}.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
