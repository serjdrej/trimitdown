from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from core.converter import convert_and_save, delete_file, list_archive, safe_path

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
