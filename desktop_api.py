from urllib.parse import urlsplit, urlunsplit

import requests
import urllib3

from config_store import get_server_url, load_config, save_config

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_CHECK_TIMEOUT = 1.5


def server_reachable(url: str) -> bool:
    """Whether the stored address answers, secret and all.

    The address may carry the server's shared secret as a query -- that is how
    the link works in a browser, in a webview and on a phone. Appending "/" to
    the string, which is what this used to do, produced `...?k=secret/` and
    turned a working link into an unreachable server.

    Known rough edge: a wrong or missing secret is refused with 401 and reads
    here as "unreachable", so a person who pastes the address without its secret
    goes looking for a network problem. Telling the two apart means returning
    more than a boolean, and the two copies of the interface that render it have
    already diverged -- that is a separate job.
    """
    parts = urlsplit(url)
    probe = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    try:
        r = requests.get(probe, timeout=SERVER_CHECK_TIMEOUT, verify=False)
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
