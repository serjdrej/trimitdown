"""HTTP- и архивный слой над чистой конверсией.

Сама конверсия живёт в trimitdown.convert и ничего не знает про HTTP. Здесь --
только то, что про UploadFile, JSONResponse, коды ответов и файлы на диске.
Держать их порознь обязательно: пакет trimitdown публикуется на PyPI как CLI и
не должен тянуть веб-стек.
"""
import asyncio
import io
import os
import zipfile
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse

# count_tokens и safe_stem -- намеренный реэкспорт, не мусор: это часть
# объявленной публичной поверхности core.converter, которую пинит
# TestPublicSurface.test_core_converter_still_exports_the_names_the_apps_import
# в tests/test_converter.py. Причина держать их разная в зависимости от имени:
# convert_and_save, convert_batch, delete_file, list_archive, safe_path и
# zip_archive_files нужны здесь потому, что их берут server_app.py и
# docker-server/app.py; count_tokens и safe_stem (а также save_unique, который
# живёт прямо в этом модуле) нужны потому, что они часть той же объявленной
# поверхности и тест-сьют упражняет их через core.converter, а не потому, что
# их зовёт приложение. Пометка линтера "unused" здесь всё равно ложная --
# удалять нечего. TIKTOKEN_CACHE_DIR этот модуль больше не выставляет -- его
# ставит trimitdown.convert при импорте, одним местом на оба слоя.
from trimitdown.convert import ConversionError, convert_bytes, count_tokens, safe_stem

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


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
    # Conversion can take several seconds on large files — offload to a thread
    # so it doesn't block the event loop for every other client. This server is
    # meant to be hit by multiple devices at once; without this, one slow
    # conversion would freeze even a simple archive listing for everyone.
    #
    # Одним вызовом вместо трёх: маршрутизация, оценка и счёт токенов теперь
    # внутри ядра, здесь остаётся только увести их с event loop.
    try:
        result = await asyncio.to_thread(convert_bytes, data, Path(file.filename).suffix)
    except ConversionError as e:
        raise HTTPException(status_code=422, detail=f"Не удалось сконвертировать файл: {e}")

    filename = save_unique(archive_dir, safe_stem(file.filename), result.text)
    return {
        "filename": filename,
        "content": result.text,
        "tokens": {
            "after": result.tokens_after,
            "before": result.tokens_before,
            "unit": result.unit,
            "units": result.units,
        },
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
