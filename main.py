import socket
import threading
import time

import requests
import urllib3
import webview

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

NAS_URL = "https://192.168.1.100:8002"
NAS_CHECK_TIMEOUT = 1.5


def nas_reachable() -> bool:
    try:
        r = requests.get(NAS_URL + "/", timeout=NAS_CHECK_TIMEOUT, verify=False)
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


def main():
    if nas_reachable():
        target = NAS_URL
    else:
        port = free_port()
        thread = threading.Thread(target=start_local_server, args=(port,), daemon=True)
        thread.start()
        if not wait_port(port):
            raise RuntimeError("Локальный сервер не запустился")
        target = f"http://127.0.0.1:{port}"

    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.create_window("MarkItDown", target, width=440, height=820, resizable=True, min_size=(360, 600))
    webview.start()


if __name__ == "__main__":
    main()
