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


TOKEN = "a-secret-for-the-tests"


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A client that already holds the shared secret.

    Every test below used to reach the archive with no credentials at all and
    call that a pass -- the audit's point exactly: the checks confirmed the door
    was open. They now go through the lock, and the tests that prove the lock
    exists are at the bottom of this file.
    """
    import app as docker_app
    monkeypatch.setattr(docker_app, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setenv("TRIMITDOWN_TOKEN", TOKEN)
    client = TestClient(docker_app.app)
    client.cookies.set(docker_app.TOKEN_COOKIE, TOKEN)
    return client


def locked_client_for(tmp_path, monkeypatch):
    """A client holding nothing, for the tests about being refused.

    A plain function rather than a fixture: the pre-commit guard that looks for
    personal data reads the fixture decorator as an email address, and the rule
    in this repository is to reword rather than to narrow the pattern.
    """
    import app as docker_app
    monkeypatch.setattr(docker_app, "ARCHIVE_DIR", tmp_path)
    monkeypatch.setenv("TRIMITDOWN_TOKEN", TOKEN)
    return TestClient(docker_app.app)


def test_convert_endpoint_converts_and_saves_a_single_file(client, monkeypatch):
    # The primary path: one file, one synchronous request. Nothing else in this
    # module ever calls TestClient against plain /api/convert -- every other
    # test here goes through /api/convert-batch, so a deleted or broken
    # single-file route would not fail a single test in this suite.
    class FakeResult:
        text_content = "converted"

    monkeypatch.setattr(pure.md, "convert", lambda path: FakeResult())

    response = client.post(
        "/api/convert",
        files={"file": ("a.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "converted"
    assert body["filename"] == "a.md"


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
    # Each event must name the upload it actually converted, not the same file
    # replayed len(files) times. A batch that silently substitutes files[0]
    # into every slot still produces the right count and an "ok" status for
    # each, so filename identity is the only thing that catches it.
    assert [e["filename"] for e in events] == ["a.txt", "b.txt"]


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

    # Status code and MIME type alone are true for an empty archive too --
    # a ZIP with zero entries is still a valid application/zip response. The
    # only way to catch a handler that forgets to actually write the files in
    # is to open the archive and check what is inside it.
    import zipfile
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert set(zf.namelist()) == {"a.md", "b.md"}
        assert zf.read("a.md").decode("utf-8") == "content A"
        assert zf.read("b.md").decode("utf-8") == "content B"


def test_mode_endpoint_returns_server_mode_and_version(client):
    from trimitdown import __version__ as VERSION

    response = client.get("/api/mode")

    assert response.status_code == 200
    assert response.json() == {"mode": "server", "version": VERSION}


class TestTheSharedSecret:
    """The lock on the door of a personal server.

    Not a user system: one archive, one person, one secret. What was missing was
    any lock at all, while `docker-compose` published the port on every
    interface -- which on a machine with a public address is the open internet,
    and Docker's own iptables rules mean a `ufw deny` on that port does not
    close it.
    """

    def test_the_archive_is_not_served_to_a_request_without_the_secret(
        self, tmp_path, monkeypatch
    ):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        (tmp_path / "private.md").write_text("someone's document", encoding="utf-8")

        listing = locked_client.get("/api/archive")
        download = locked_client.get("/api/archive/private.md")
        removal = locked_client.delete("/api/archive/private.md")

        assert listing.status_code == 401
        assert download.status_code == 401
        assert removal.status_code == 401
        assert "someone's document" not in download.text
        # And the refusal did not delete it either.
        assert (tmp_path / "private.md").exists()

    def test_conversion_is_not_performed_for_a_request_without_the_secret(
        self, tmp_path, monkeypatch
    ):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        response = locked_client.post(
            "/api/convert", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}
        )

        assert response.status_code == 401

    def test_a_link_carrying_the_secret_opens_the_server_and_leaves_a_cookie(
        self, tmp_path, monkeypatch
    ):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        import app as docker_app

        response = locked_client.get(f"/api/mode?{docker_app.TOKEN_PARAM}={TOKEN}")

        assert response.status_code == 200
        assert response.json()["mode"] == "server"
        # The secret stops travelling in URLs after the first visit, and the
        # front end -- which exists in two diverged copies -- needs to know
        # nothing about any of this.
        assert locked_client.cookies.get(docker_app.TOKEN_COOKIE) == TOKEN

    def test_a_wrong_secret_is_refused(self, tmp_path, monkeypatch):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        response = locked_client.get("/api/mode?k=not-the-secret")

        assert response.status_code == 401
        assert locked_client.cookies.get("trimitdown_key") is None

    def test_a_server_with_no_secret_configured_refuses_to_serve(
        self, tmp_path, monkeypatch
    ):
        # The dangerous default is the one that keeps working. An unset secret
        # used to mean "no protection at all", and that disagreed with what
        # SECURITY.md promised the reader.
        import app as docker_app

        monkeypatch.setattr(docker_app, "ARCHIVE_DIR", tmp_path)
        monkeypatch.delenv("TRIMITDOWN_TOKEN", raising=False)
        client = TestClient(docker_app.app)

        response = client.get("/api/archive")

        assert response.status_code == 503
        assert "TRIMITDOWN_TOKEN" in response.json()["detail"]

    def test_the_static_files_are_behind_the_lock_too(self, tmp_path, monkeypatch):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        # A mounted StaticFiles app is easy to leave outside a check that only
        # decorates routes. The UI is not a secret, but the same mount is how a
        # reader would learn the server is there at all.
        assert locked_client.get("/static/app.js").status_code == 401

    def test_a_forged_cookie_is_refused(self, tmp_path, monkeypatch):
        locked_client = locked_client_for(tmp_path, monkeypatch)
        # The cookie is what every request after the first one carries, so it is
        # the path that matters most -- and it is trivially set by hand. A test
        # that only checks a wrong secret in the link leaves this whole branch
        # unguarded: measured, removing the comparison here kept the file green.
        import app as docker_app

        locked_client.cookies.set(docker_app.TOKEN_COOKIE, "not-the-secret")

        response = locked_client.get("/api/archive")

        assert response.status_code == 401
