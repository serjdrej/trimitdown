import re
import tempfile
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, UploadFile
from fastapi.responses import JSONResponse
from markitdown import MarkItDown

md = MarkItDown()


def safe_stem(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-. ]", "_", stem, flags=re.UNICODE).strip()
    return stem or "file"


def unique_target(archive_dir: Path, stem: str) -> Path:
    target = archive_dir / f"{stem}.md"
    if not target.exists():
        return target
    i = 2
    while True:
        candidate = archive_dir / f"{stem} ({i}).md"
        if not candidate.exists():
            return candidate
        i += 1


def safe_path(archive_dir: Path, filename: str) -> Path:
    path = (archive_dir / filename).resolve()
    if archive_dir.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return path


async def convert_and_save(archive_dir: Path, file: UploadFile) -> JSONResponse:
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
    target = unique_target(archive_dir, safe_stem(file.filename))
    target.write_text(text, encoding="utf-8")

    return JSONResponse({"filename": target.name, "content": text})


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
