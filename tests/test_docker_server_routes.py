import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "docker-server"))

import pytest
from fastapi.testclient import TestClient

# Конверсию подменяем на её собственном модуле: core.converter теперь только
# зовёт ядро и объектом markitdown не владеет. Сам docker-server/app.py при
# расщеплении не менялся -- он берёт те же имена из core.converter.
from trimitdown import convert as pure


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(pure, "md", pure.md)  # no-op, keeps import order explicit
    import app as docker_app
    monkeypatch.setattr(docker_app, "ARCHIVE_DIR", tmp_path)
    return TestClient(docker_app.app)


def test_convert_batch_streams_one_event_per_file(client, monkeypatch):
    class FakeResult:
        text_content = "converted"

    monkeypatch.setattr(pure.md, "convert", lambda path: FakeResult())

    files = [
        ("files", ("a.txt", io.BytesIO(b"one"), "text/plain")),
        ("files", ("b.txt", io.BytesIO(b"two"), "text/plain")),
    ]
    response = client.post("/api/convert-batch", files=files)

    assert response.status_code == 200
    events = [
        json.loads(line[len("data: "):])
        for line in response.text.split("\n\n")
        if line.startswith("data: ")
    ]
    assert len(events) == 2
    assert {e["status"] for e in events} == {"ok"}


def test_convert_batch_rejects_more_than_10_files(client):
    files = [("files", (f"{i}.txt", io.BytesIO(b"x"), "text/plain")) for i in range(11)]
    response = client.post("/api/convert-batch", files=files)
    assert response.status_code == 400


def test_archive_zip_downloads_requested_files(client, tmp_path):
    (tmp_path / "a.md").write_text("content A", encoding="utf-8")
    (tmp_path / "b.md").write_text("content B", encoding="utf-8")

    response = client.get("/api/archive-zip", params={"names": "a.md,b.md"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"


def test_mode_endpoint_returns_server_mode_and_version(client):
    from trimitdown import __version__ as VERSION

    response = client.get("/api/mode")

    assert response.status_code == 200
    assert response.json() == {"mode": "server", "version": VERSION}
