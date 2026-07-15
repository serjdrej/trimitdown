import asyncio
import io
import os
import re
import tempfile
import zipfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import tiktoken
from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse
from markitdown import MarkItDown
from pdfminer.pdfpage import PDFPage
from pptx import Presentation

md = MarkItDown()

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB

os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(Path(__file__).parent / "tiktoken_cache"))
TOKENS_PER_UNIT_ESTIMATE = 2250  # midpoint of the documented 1500-3000 tokens/page vision-estimate
                                  # range (Anthropic docs) — used for the PDF/PPTX before/after
                                  # comparison only. The frontend never renders a negative saving:
                                  # if a dense page's extracted text still exceeds this estimate,
                                  # it shows the raw result-token count with no percentage.
_encoding = None


def _get_encoding():
    global _encoding
    if _encoding is None:
        _encoding = tiktoken.get_encoding("cl100k_base")
    return _encoding


def count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


def _count_pdf_pages(path: Path) -> int:
    with open(path, "rb") as f:
        return len(list(PDFPage.get_pages(f)))


def _count_pptx_slides(path: Path) -> int:
    return len(Presentation(path).slides)


def _estimate_before_tokens(suffix: str, tmp_path: str) -> tuple[int | None, str | None, int | None]:
    try:
        if suffix == ".pdf":
            units = _count_pdf_pages(Path(tmp_path))
            return units * TOKENS_PER_UNIT_ESTIMATE, "page", units
        if suffix == ".pptx":
            units = _count_pptx_slides(Path(tmp_path))
            return units * TOKENS_PER_UNIT_ESTIMATE, "slide", units
    except Exception:
        pass
    return None, None, None


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-. ]", "_", stem, flags=re.UNICODE).strip()
    return stem or "file"


def _candidate_names(stem: str):
    yield f"{stem}.md"
    i = 2
    while True:
        yield f"{stem} ({i}).md"
        i += 1


def save_unique(archive_dir: Path, stem: str, text: str) -> str:
    # Atomic create-exclusive instead of exists()-then-write(): two concurrent
    # conversions with the same filename (realistic here — several devices share
    # one archive) could otherwise both pass the exists() check for "file.md" and
    # the second write would silently clobber the first instead of falling back
    # to "file (2).md".
    for name in _candidate_names(stem):
        path = archive_dir / name
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        return name


def safe_path(archive_dir: Path, filename: str) -> Path:
    path = (archive_dir / filename).resolve()
    if archive_dir.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return path


def zip_archive_files(archive_dir: Path, filenames: list[str]) -> io.BytesIO:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in filenames:
            path = safe_path(archive_dir, name)
            zf.write(path, arcname=name)
    buffer.seek(0)
    return buffer


async def _convert_one(archive_dir: Path, file: UploadFile) -> dict:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Файл слишком большой (максимум 200 МБ) / File too large (200 MB max)",
        )
    suffix = Path(file.filename).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        # md.convert() can take several seconds on large PDFs/OCR — offload to a
        # thread so it doesn't block the event loop for every other client. This
        # server is meant to be hit by multiple devices at once; without this, one
        # slow conversion would freeze even a simple archive listing for everyone.
        result = await asyncio.to_thread(md.convert, tmp_path)
    except Exception as e:
        Path(tmp_path).unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Не удалось сконвертировать файл: {e}")

    # Page/slide counting needs the temp file to still exist on disk, so this runs
    # before the cleanup unlink below (unlike the try/except above, which unlinks
    # early only on the failure path).
    before, unit, units = await asyncio.to_thread(_estimate_before_tokens, suffix.lower(), tmp_path)
    Path(tmp_path).unlink(missing_ok=True)

    filename = save_unique(archive_dir, safe_stem(file.filename), result.text_content)
    after = count_tokens(result.text_content)
    return {
        "filename": filename,
        "content": result.text_content,
        "tokens": {"after": after, "before": before, "unit": unit, "units": units},
    }


async def convert_and_save(archive_dir: Path, file: UploadFile) -> JSONResponse:
    return JSONResponse(await _convert_one(archive_dir, file))


async def convert_batch(archive_dir: Path, files: list[UploadFile]) -> AsyncIterator[dict]:
    for file in files:
        try:
            data = await _convert_one(archive_dir, file)
            yield {"filename": file.filename, "status": "ok", "saved_as": data["filename"]}
        except HTTPException as e:
            yield {"filename": file.filename, "status": "error", "detail": e.detail}


def list_archive(archive_dir: Path, q: str = "") -> list[dict]:
    items = []
    for p in sorted(archive_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
        if q and q.lower() not in p.name.lower():
            continue
        st = p.stat()
        items.append({
            "filename": p.name,
            "size": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
        })
    return items


def delete_file(archive_dir: Path, filename: str) -> None:
    safe_path(archive_dir, filename).unlink()
