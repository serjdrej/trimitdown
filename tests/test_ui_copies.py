"""Behaviours that must not differ between the two copies of the interface.

There are two: `static/` inside the desktop bundle, and `docker-server/static/`
served by the self-hosted server -- and, when the desktop opens a remote server,
loaded inside the desktop's own webview. Most of their differences are
deliberate: an inventory of all 245 changed lines put 215 of them in the
"intentional" bucket (shared archive, service worker, download paths, cert link)
and none in "dead".

The other 30 were drift, both times with the Docker copy behind, and both times
user-visible. This file pins the two so they cannot drift apart again while the
copies remain separate.

These are text assertions over JavaScript -- there is no JS runtime in this
suite, and this file does not pretend to exercise the behaviour. What it can do
is refuse a copy that has lost the fix, which is the failure that actually
happened.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DESKTOP = REPO_ROOT / "static" / "app.js"
SERVER = REPO_ROOT / "docker-server" / "static" / "app.js"


def _top_level_function(source, signature):
    """The function from its signature to the first closing brace in column 0."""
    start = source.index(signature)
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


def test_both_copies_read_a_failed_response_as_text_first():
    """Reverting either copy to `(await res.json()).detail` must fail this test.

    A server exception returns plain text, and calling res.json() on it throws
    its own "Unexpected token" -- so the user is shown a parser error instead of
    what actually went wrong, and the real failure is lost. The Docker copy did
    this until the inventory found it.
    """
    signature = "async function errorDetail(res) {"
    desktop = DESKTOP.read_text(encoding="utf-8")
    server = SERVER.read_text(encoding="utf-8")

    assert signature in desktop
    assert signature in server
    # Present in both is not enough: the point is that they behave the same.
    assert _top_level_function(desktop, signature) == _top_level_function(
        server, signature
    )
    for source in (desktop, server):
        assert "(await res.json()).detail" not in source, (
            "a call site still parses a failed response as JSON directly"
        )


def test_both_copies_wait_for_pywebview_before_showing_the_server_address():
    """Reverting either copy to a synchronous check must fail this test.

    pywebview injects its API asynchronously. A copy that checks for it at script
    load loses the race in the packaged application and leaves the server-address
    controls hidden -- in the one mode where the address is what a person came to
    change. The Docker copy is the one the desktop loads when it opens a remote
    server, so it was losing that race exactly where it mattered.
    """
    dispatch = 'window.addEventListener("pywebviewready", setupServerSettings);'

    for path in (DESKTOP, SERVER):
        source = path.read_text(encoding="utf-8")
        assert dispatch in source, f"{path.name} does not wait for pywebviewready"
        assert re.search(
            r"function setupServerSettings\(\)\s*\{", source
        ), f"{path.name} has no setupServerSettings to defer"
