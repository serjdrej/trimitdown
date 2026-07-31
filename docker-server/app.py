import json
import os
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from core.converter import convert_and_save, convert_batch, delete_file, list_archive, safe_path, zip_archive_files
# Единственный источник версии на весь проект -- пакет. Отдельный core/version.py
# существовал до того, как приложение стало устанавливаемым, и держал второе
# число, которое было обязано совпадать с первым, но ничем к этому не
# принуждалось.
from trimitdown import __version__ as VERSION

# The real container already guarantees this exists: the Dockerfile creates it
# at build time and docker-compose bind-mounts a host directory over it at
# runtime. Creating it here too was a module-level side effect that ran on
# every import -- including in tests, where it tried to mkdir a literal /app
# on whatever machine runs pytest and failed outside a container. Tests
# monkeypatch ARCHIVE_DIR after import anyway (see test_docker_server_routes.py),
# so nothing here depends on this path existing at import time.
ARCHIVE_DIR = Path("/app/archive")

app = FastAPI()

# One shared secret, not a user system. The server is a personal tool: it holds
# one archive, belongs to one person, and has never claimed otherwise. What it
# lacked was a lock on the door, and `docker-compose` publishes its port on every
# interface -- on a VPS that is the open internet, and Docker writes its own
# iptables rules, so a `ufw deny` on that port does not close it.
#
# Delivered as a link rather than an HTTP Basic prompt. The desktop app in server
# mode opens the remote address inside a webview, and WKWebView on macOS shows no
# native authentication dialog unless the host application implements the
# challenge handler -- which pywebview does not. A lock that silently breaks one
# platform is the shape of defect this project has paid for three times. A link
# works in a webview, in Safari and in a home-screen PWA, and needs no change in
# the front end -- which matters, because there are two copies of it and they
# have already diverged.
TOKEN_COOKIE = "trimitdown_key"
TOKEN_PARAM = "k"


def _configured_token() -> str:
    """The secret, or a refusal to start without one.

    Read at request time rather than at import so the tests can set it, and so a
    container started without it fails on the first request with a message that
    says what to do -- instead of serving the archive to anyone who asks.
    """
    return os.environ.get("TRIMITDOWN_TOKEN", "")


async def require_the_shared_secret(request: Request, call_next):
    token = _configured_token()
    if not token:
        # Refusing is the point. An unset secret used to mean "no protection",
        # and that default disagreed with what SECURITY.md promised.
        return JSONResponse(
            status_code=503,
            content={
                "detail": "TRIMITDOWN_TOKEN is not set. Generate one "
                "(`openssl rand -hex 24`), put it in docker-server/.env, and "
                "restart. The server refuses to serve without it."
            },
        )

    supplied = request.query_params.get(TOKEN_PARAM)
    if supplied is not None and secrets.compare_digest(supplied, token):
        # Arrived by link: keep it for every later request so the secret stops
        # travelling in URLs, and so the front end needs to know nothing.
        response = await call_next(request)
        response.set_cookie(
            TOKEN_COOKIE,
            token,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 365,
        )
        return response

    cookie = request.cookies.get(TOKEN_COOKIE)
    if cookie is not None and secrets.compare_digest(cookie, token):
        return await call_next(request)

    return JSONResponse(
        status_code=401,
        content={"detail": "Open this server with your personal link."},
    )


app.add_middleware(BaseHTTPMiddleware, dispatch=require_the_shared_secret)
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
    return FileResponse(cert_path, media_type="application/x-x509-ca-cert", filename="trimitdown.cer")


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
