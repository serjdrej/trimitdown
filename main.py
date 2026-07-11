import platform
import socket
import subprocess
import sys
import threading
import time

import requests
import urllib3
import webview

from config_store import ensure_config_exists, get_server_url

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_CHECK_TIMEOUT = 1.5


def server_reachable(url: str) -> bool:
    try:
        r = requests.get(url + "/", timeout=SERVER_CHECK_TIMEOUT, verify=False)
        return r.status_code == 200
    except Exception:
        return False


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


def start_local_server(port: int):
    import uvicorn
    from server_app import app
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def show_fatal_error(message: str) -> None:
    # Built --noconsole, so an uncaught exception here is otherwise completely
    # invisible — the process just exits with nothing on screen at all.
    if platform.system() == "Windows":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, "MarkItDown", 0x10)
    elif platform.system() == "Darwin":
        safe_message = message.replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'display alert "MarkItDown" message "{safe_message}"'])


def main():
    ensure_config_exists()
    server_url = get_server_url()

    if server_url and server_reachable(server_url):
        target = server_url
    else:
        port = free_port()
        thread = threading.Thread(target=start_local_server, args=(port,), daemon=True)
        thread.start()
        if not wait_port(port):
            show_fatal_error(
                "Не удалось запустить локальный сервер. Попробуйте перезапустить приложение.\n\n"
                "Local server failed to start. Try restarting the app."
            )
            sys.exit(1)
        target = f"http://127.0.0.1:{port}"

    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.create_window("MarkItDown", target, width=440, height=820, resizable=True, min_size=(360, 600))
    webview.start()


if __name__ == "__main__":
    main()
