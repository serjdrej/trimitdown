import json
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.converter import convert_and_save, convert_batch, delete_file, list_archive, safe_path, zip_archive_files
from core.version import VERSION

ARCHIVE_DIR = Path("/app/archive")
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI()
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


@app.get("/api/mode")
def mode():
    return {"mode": "server", "version": VERSION}


@app.get("/cert")
def get_cert():
    cert_path = Path("/certs/cert.pem")
    if not cert_path.exists():
        raise HTTPException(404, "cert not found")
    return FileResponse(cert_path, media_type="application/x-x509-ca-cert", filename="markitdown-nas.cer")


@app.post("/api/convert")
async def convert(file: UploadFile = File(...)):
    return await convert_and_save(ARCHIVE_DIR, file)


@app.get("/api/archive")
def archive(q: str = ""):
    return list_archive(ARCHIVE_DIR, q)


@app.get("/api/archive/{filename}")
def download(filename: str, raw: int = 0):
    # raw=1 (sent only by pywebview desktop clients, see app.js): those embedded webviews
    # decide render-vs-download by whether they can display the MIME type inline, ignoring
    # Content-Disposition, so they need application/octet-stream to force a download.
    # Regular browsers get text/markdown back — octet-stream has no type info, and iOS Safari
    # falls back to sniffing the raw bytes for a preview, sometimes misdetecting them as HTML.
    media_type = "application/octet-stream" if raw else "text/markdown"
    return FileResponse(safe_path(ARCHIVE_DIR, filename), filename=filename, media_type=media_type)


@app.delete("/api/archive/{filename}")
def delete(filename: str):
    delete_file(ARCHIVE_DIR, filename)
    return {"ok": True}


@app.post("/api/convert-batch")
async def convert_batch_endpoint(files: list[UploadFile] = File(...)):
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
