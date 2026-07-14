import requests
import urllib3

from config_store import get_server_url, load_config, save_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_CHECK_TIMEOUT = 1.5


def server_reachable(url: str) -> bool:
    try:
        r = requests.get(url + "/", timeout=SERVER_CHECK_TIMEOUT, verify=False)
        return r.status_code == 200
    except Exception:
        return False


class Api:
    def get_server_url(self) -> str | None:
        return get_server_url()

    def save_server_url(self, url: str) -> None:
        config = load_config()
        config["server_url"] = url or None
        save_config(config)

    def check_reachable(self, url: str) -> bool:
        return server_reachable(url)
