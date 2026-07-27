import os
import platform
import socket
import subprocess
import sys
import threading
import time
import traceback

from config_store import ensure_config_exists, get_server_url
from desktop_api import Api, server_reachable
from trimitdown import __version__ as VERSION

# Set to a document path, the app converts it headlessly and exits instead of
# opening a window. See smoke() for why this lives in the shipped binary.
SMOKE_ENV = "TRIMITDOWN_SMOKE"
# Where smoke mode writes what happened. See _smoke_report.
SMOKE_LOG_ENV = "TRIMITDOWN_SMOKE_LOG"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_port(port: int, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def start_local_server(port: int, failure: list[str] | None = None):
    # These imports run inside the server thread, and this is where every macOS
    # bundle before 0.1.1 died: server_app -> core.converter -> trimitdown.convert
    # -> pdfminer -> cryptography, whose _rust extension dlopen'd a libssl too
    # old for it. A thread that raises writes to stderr, and a --noconsole build
    # has no stderr -- so the user saw "the server did not start" and the one
    # sentence naming the cause was discarded. Keep it and show it.
    try:
        import uvicorn
        from server_app import app
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    except BaseException:
        if failure is not None:
            failure.append(traceback.format_exc())
        raise


def start_server_thread() -> tuple[int, list[str]]:
    port = free_port()
    failure: list[str] = []
    threading.Thread(target=start_local_server, args=(port, failure), daemon=True).start()
    return port, failure


def _smoke_report(message: str) -> None:
    """Write where CI can read it, because a windowed build has nowhere else.

    The Windows exe is built console=False, which leaves sys.stdout and
    sys.stderr set to None: a plain print() in this path raises AttributeError
    and replaces the message explaining the failure with an unrelated one. The
    log file is therefore the evidence, not a convenience -- CI asserts on it
    rather than on an exit code, which a GUI-subsystem process does not always
    deliver to the shell that started it.
    """
    line = message.rstrip() + "\n"
    path = os.environ.get(SMOKE_LOG_ENV)
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line)
    if sys.stderr is not None:
        sys.stderr.write(line)


def smoke(document: str) -> int:
    """Run the smoke conversion and make sure its failure is never silent."""
    try:
        return _smoke(document)
    except BaseException:
        # Any failure at all -- a missing dylib, a toolkit that needs a display,
        # a broken entry point -- has to arrive in the log naming itself. The
        # 0.1.0 bundles failed with nothing but "the server did not start".
        _smoke_report(traceback.format_exc())
        return 1


def _smoke(document: str) -> int:
    """Convert one document through the real server, then exit. No window.

    This exists because a bundle that contains every file it needs still dies
    on the first dlopen, and the check that greps the build manifest cannot see
    the difference -- it looks at names, not at whether the process runs. The
    only check that can is the shipped binary doing the actual work, so CI
    drives this path on every build. It is deliberately in the product and not
    in a test harness: a harness would exercise the source tree, which is not
    the artifact that reaches users and not the artifact that was broken.
    """
    import requests

    port, failure = start_server_thread()
    if not wait_port(port):
        _smoke_report(failure[0] if failure else
                     "the server thread never bound the port and reported nothing\n")
        return 1

    base = f"http://127.0.0.1:{port}"
    mode = requests.get(f"{base}/api/mode", timeout=30).json()
    # Proves the port answers *because of us*. Any HTTP 200 would otherwise pass.
    if mode.get("version") != VERSION:
        _smoke_report(f"/api/mode answered {mode!r}, expected version {VERSION}\n")
        return 1

    with open(document, "rb") as fh:
        response = requests.post(f"{base}/api/convert",
                                 files={"file": (os.path.basename(document), fh)},
                                 timeout=300)
    if response.status_code != 200:
        _smoke_report(f"/api/convert returned {response.status_code}: {response.text[:500]}\n")
        return 1

    body = response.json()
    if not body.get("content"):
        _smoke_report(f"conversion produced no markdown: {body!r}\n")
        return 1
    # None here is the tokenizer having failed while the conversion succeeded --
    # the exact state the UI mishandles, and invisible to a status-code check.
    if not isinstance(body.get("tokens", {}).get("after"), int):
        _smoke_report(f"token count is not a number: {body.get('tokens')!r}\n")
        return 1

    # The window itself is the one part smoke mode cannot exercise -- a CI
    # runner has no display. Importing the toolkit is weaker than opening a
    # window and stronger than a grep over the build manifest: it proves the
    # package was bundled and that it loads in this process. If this import
    # turns out to need a display, the check has to become a bundle-contents
    # assertion instead; that would be measured, not assumed.
    import webview  # noqa: F401

    _smoke_report(f"smoke ok: {len(body['content'])} chars, {body['tokens']['after']} tokens")
    return 0


def show_fatal_error(message: str) -> None:
    # Built --noconsole, so an uncaught exception here is otherwise completely
    # invisible — the process just exits with nothing on screen at all.
    if platform.system() == "Windows":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "TrimItDown", 0x10)
    elif platform.system() == "Darwin":
        safe_message = message.replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "TrimItDown" message "{safe_message}"'])


def main():
    smoke_document = os.environ.get(SMOKE_ENV)
    if smoke_document:
        sys.exit(smoke(smoke_document))

    ensure_config_exists()
    server_url = get_server_url()

    if server_url and server_reachable(server_url):
        target = server_url
    else:
        port, failure = start_server_thread()
        if not wait_port(port):
            # The last line of the traceback is the diagnosis -- for the 0.1.0
            # bundles it was the dlopen error naming the missing symbol. The
            # whole traceback would not fit an alert box; that line does.
            detail = failure[0].strip().splitlines()[-1] if failure else ""
            show_fatal_error(
                "Не удалось запустить локальный сервер. Попробуйте перезапустить приложение.\n\n"
                "Local server failed to start. Try restarting the app."
                + (f"\n\n{detail}" if detail else "")
            )
            sys.exit(1)
        target = f"http://127.0.0.1:{port}"

    # Imported here, not at module scope: the GUI toolkit is the one dependency
    # smoke mode has no use for, and on a headless runner importing it is at
    # best pointless. It also keeps this module importable by the test suite,
    # which runs on Linux without a display.
    import webview

    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.create_window("TrimItDown", target, width=440, height=820, resizable=True, min_size=(360, 600), js_api=Api())
    webview.start()


if __name__ == "__main__":
    main()
