"""The launch path of the desktop app: failure has to be legible, not silent.

Every macOS bundle up to 0.1.0 died on import inside the server thread and the
user was told only that the server had not started. These tests are about the
sentence that was thrown away, and about the smoke mode CI uses to run the real
binary instead of grepping the build manifest.
"""
import sys

import pytest

import main


def test_server_thread_failure_is_captured_not_swallowed(monkeypatch):
    """The traceback must survive the thread that produced it.

    Weakened -- asserting only that start_local_server raises -- this passes
    with the try/except deleted, which is precisely the state that shipped:
    the exception went to a stderr that a --noconsole build does not have.
    """
    monkeypatch.setitem(sys.modules, "server_app", None)
    failure: list[str] = []

    with pytest.raises(ImportError):
        main.start_local_server(0, failure)

    assert failure, "the server thread raised and left nothing behind"
    assert "Traceback" in failure[0] and "server_app" in failure[0], \
        "the captured text must name where the import died, not just that it did"


def test_fatal_error_names_the_cause(monkeypatch):
    """The alert must carry the diagnosis, not just the symptom.

    Weakened to 'a message was shown', it passes with the detail dropped --
    and the user is back to a dialog that names no cause. The line asserted
    here is the shape of the real one: the dlopen error and its missing symbol.
    """
    shown: list[str] = []
    monkeypatch.setattr(main, "ensure_config_exists", lambda: None)
    monkeypatch.setattr(main, "get_server_url", lambda: None)
    monkeypatch.setattr(main, "wait_port", lambda port, timeout=15: False)
    monkeypatch.setattr(main, "show_fatal_error", lambda message: shown.append(message))
    monkeypatch.setattr(main, "start_server_thread", lambda: (1, [
        "Traceback (most recent call last):\n"
        "ImportError: dlopen(_rust.abi3.so): Symbol not found: _SSL_get0_group_name\n"
    ]))

    with pytest.raises(SystemExit) as exit_info:
        main.main()

    assert exit_info.value.code == 1
    assert "Symbol not found: _SSL_get0_group_name" in shown[0]


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)

    def json(self):
        return self._payload


def _fake_requests(monkeypatch, convert_payload, status_code=200, version=main.VERSION):
    """Drive smoke() without a socket. The real server is CI's job, not this test's."""
    module = type(sys)("requests")
    module.get = lambda url, timeout=None: _Response({"mode": "local", "version": version})
    module.post = lambda url, files=None, timeout=None: _Response(convert_payload, status_code)
    monkeypatch.setitem(sys.modules, "requests", module)


OK_PAYLOAD = {"filename": "x.md", "content": "# heading\n", "tokens": {"after": 3, "before": 9}}


def test_smoke_passes_on_a_real_conversion(monkeypatch, tmp_path):
    document = tmp_path / "doc.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(main, "start_server_thread", lambda: (1, []))
    monkeypatch.setattr(main, "wait_port", lambda port, timeout=15: True)
    _fake_requests(monkeypatch, OK_PAYLOAD)

    assert main.smoke(str(document)) == 0


def test_smoke_fails_on_a_conversion_that_only_looks_successful(monkeypatch, tmp_path):
    """HTTP 200 is not the guarantee -- the output is.

    Each case returns 200 with a body the UI cannot use. A smoke check that
    stopped at the status code would call all three a success; the second is
    the null-token state that makes the UI report a failed conversion for a
    conversion that in fact succeeded and was already saved to the archive.

    Written as a loop rather than the usual pytest decorator on purpose: the
    decorator's line reads as an email address to the PII hook, and the rule
    for a false positive is to reword the line, never to bypass the guard.
    """
    document = tmp_path / "doc.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(main, "start_server_thread", lambda: (1, []))
    monkeypatch.setattr(main, "wait_port", lambda port, timeout=15: True)

    cases = [
        ("empty markdown", {"filename": "x.md", "content": "", "tokens": {"after": 3}}),
        ("tokenizer failed", {"filename": "x.md", "content": "# h\n", "tokens": {"after": None}}),
        ("no token block at all", {"filename": "x.md", "content": "# h\n"}),
    ]
    for reason, payload in cases:
        _fake_requests(monkeypatch, payload)
        assert main.smoke(str(document)) == 1, reason


def test_smoke_fails_when_the_port_answers_for_someone_else(monkeypatch, tmp_path):
    """A stray HTTP 200 on the port must not count as our server.

    Without the version check this passes on any process that happens to hold
    the port -- the same false equality the desktop reachability check makes.
    """
    document = tmp_path / "doc.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(main, "start_server_thread", lambda: (1, []))
    monkeypatch.setattr(main, "wait_port", lambda port, timeout=15: True)
    _fake_requests(monkeypatch, OK_PAYLOAD, version="99.0.0")

    assert main.smoke(str(document)) == 1


def test_smoke_reports_the_import_failure_when_the_server_never_starts(
        monkeypatch, tmp_path, capsys):
    """The CI log has to name the cause, or the next diagnosis costs a day again."""
    document = tmp_path / "doc.pdf"
    document.write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(main, "start_server_thread",
                        lambda: (1, ["ImportError: dlopen failed\n"]))
    monkeypatch.setattr(main, "wait_port", lambda port, timeout=15: False)

    assert main.smoke(str(document)) == 1
    assert "dlopen failed" in capsys.readouterr().err


def test_webview_is_not_imported_at_module_scope():
    """main.py must stay importable on a headless Linux runner.

    The suite runs on ubuntu-latest with no display, and this whole file
    imports main. Move the pywebview import back to module scope and this test
    says so here, instead of CI saying it as a collection error across every
    test in the file.
    """
    assert not hasattr(main, "webview"), (
        "pywebview imported at module scope: it makes main.py unimportable "
        "without a display and drags the GUI toolkit into smoke mode")
