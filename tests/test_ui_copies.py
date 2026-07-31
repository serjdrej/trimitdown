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
import difflib
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# The divergence budget.
#
# The two tests above pin specific behaviours that must be identical. Everything
# below is a different, complementary check: it does not care what the two
# copies say, only whether every difference between them was anticipated.
#
# STATIC_DIR (the desktop bundle) and SERVER_DIR (the self-hosted server, and
# what the desktop's own webview loads when it opens a remote server) started as
# one fork and have been hand-edited on both sides since. An inventory of every
# differing line put most of them in one of five buckets below. ALLOWED_DIFFERENCES
# is that inventory, made executable: each entry names a file, a category, a
# reason, and a marker distinctive enough to survive a rewording of the
# surrounding lines without also matching some unrelated hunk.
#
# A hunk that matches no entry is drift that nobody wrote down -- the same
# failure mode `test_both_copies_*` above exists to catch, just before it ships
# rather than after. An entry that matches no hunk is stale: either the
# difference was quietly resynced, or a deliberate divergence got reverted by
# accident. Both are worth a red build, because both are cheapest to answer at
# the moment someone is already looking at the diff.
# ---------------------------------------------------------------------------

STATIC_DIR = REPO_ROOT / "static"
SERVER_DIR = REPO_ROOT / "docker-server" / "static"

# The three JS/CSS files plus the page that loads them. server_app.py and
# docker-server/app.py are separate modules by design and out of scope here.
FRONTEND_FILES = ("app.js", "index.html", "style.css", "sw.js")


@dataclass(frozen=True)
class AllowedDifference:
    file: str  # one of FRONTEND_FILES
    category: str
    marker: str  # substring that must appear in the matching diff hunk
    reason: str


ALLOWED_DIFFERENCES = [
    AllowedDifference(
        file="app.js",
        category="remote desktop-shell identification",
        marker="markDesktopShell",
        reason=(
            "docker-server/static is served both to the iOS PWA and to the "
            "desktop shell when it opens a remote server, so only that copy "
            "needs to tag itself as pywebview at runtime; the desktop bundle's "
            "own copy runs nowhere else and gets the desktop spacing by default."
        ),
    ),
    AllowedDifference(
        file="app.js",
        category="server certificate UI",
        marker="certHint",
        reason=(
            "The Docker server has a /cert route for installing its TLS "
            "certificate on iOS; the desktop app has no such route to link to, "
            "so it carries neither the string nor the element lookup."
        ),
    ),
    AllowedDifference(
        file="app.js",
        category="explanatory comment only, no behaviour difference",
        marker="This copy is the one the desktop loads",
        reason=(
            "Both copies already dispatch setupServerSettings identically "
            "(pinned above by "
            "test_both_copies_wait_for_pywebview_before_showing_the_server_address); "
            "only docker-server/static carries the extra comment explaining why "
            "that deferral matters specifically for the copy the desktop loads "
            "remotely."
        ),
    ),
    AllowedDifference(
        file="app.js",
        category="download behaviour",
        marker="isStandalonePWA",
        reason=(
            "The desktop's local backend always answers with octet-stream, so "
            "static/app.js only ever needs a direct <a download> click. "
            "docker-server/static is reached by three different runtimes -- "
            "pywebview (forced download via ?raw=1), a plain browser (blob "
            "download), and an installed iOS PWA (no reliable download, so it "
            "falls back to the Web Share sheet) -- and has to pick between them "
            "at call time."
        ),
    ),
    AllowedDifference(
        file="index.html",
        category="server certificate UI",
        marker="cert-hint",
        reason=(
            "The settings-page link to the Docker server's /cert route; the "
            "desktop app has nothing at that path, so its markup has no link."
        ),
    ),
    AllowedDifference(
        file="style.css",
        category="PWA versus desktop-shell spacing",
        marker="safe-area-inset-bottom) + 2px",
        reason=(
            "docker-server/static's default spacing assumes an iOS PWA behind a "
            "safe-area inset; the desktop bundle is always inside its own "
            "window chrome, so its default bakes in the 18px the server copy "
            "only applies once `.desktop-shell` is detected at runtime (see the "
            "next entry)."
        ),
    ),
    AllowedDifference(
        file="style.css",
        category="PWA versus desktop-shell spacing",
        marker=".desktop-shell",
        reason=(
            "The override rules that give docker-server/static its desktop "
            "spacing once app.js's markDesktopShell tags the document -- see "
            "the 'remote desktop-shell identification' entry for app.js. The "
            "desktop bundle needs no such override; it is that spacing by default."
        ),
    ),
    AllowedDifference(
        file="sw.js",
        category="service-worker cache identity",
        marker="trimitdown-shell-v",
        reason=(
            "Each deployment caches a different shell (different app.js, "
            "different index.html), so the two copies are expected to be on "
            "different cache-name generations; this entry exists so that a "
            "future generation bump on one side does not need its own allow-list "
            "edit -- the marker matches any version suffix."
        ),
    ),
]


def _diff_hunks(desktop_text: str, server_text: str) -> list[str]:
    """Unified-diff hunks (header line plus body) between the two copies of one file.

    Uses difflib rather than shelling out to git so the test has no dependency
    on git being on PATH or on repo state (staged/unstaged, working tree vs.
    index) -- it always compares the files on disk, which is what a developer
    editing them sees.
    """
    diff_lines = difflib.unified_diff(
        desktop_text.splitlines(keepends=True),
        server_text.splitlines(keepends=True),
        fromfile="static",
        tofile="docker-server/static",
    )
    hunks: list[str] = []
    current: list[str] = []
    for line in diff_lines:
        if line.startswith("@@"):
            if current:
                hunks.append("".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        hunks.append("".join(current))
    return hunks


def _classify_differences():
    """Every hunk across FRONTEND_FILES, split into matched-and-unmatched.

    Returns (unmatched, used_markers): unmatched is a list of (filename, hunk)
    pairs for hunks no allow-list entry explains; used_markers is the set of
    (file, marker) pairs that matched at least one hunk, for the staleness
    check below.
    """
    unmatched: list[tuple[str, str]] = []
    used_markers: set[tuple[str, str]] = set()

    for filename in FRONTEND_FILES:
        desktop_text = (STATIC_DIR / filename).read_text(encoding="utf-8")
        server_text = (SERVER_DIR / filename).read_text(encoding="utf-8")
        entries = [e for e in ALLOWED_DIFFERENCES if e.file == filename]

        for hunk in _diff_hunks(desktop_text, server_text):
            matches = [e for e in entries if e.marker in hunk]
            if not matches:
                unmatched.append((filename, hunk))
            for entry in matches:
                used_markers.add((entry.file, entry.marker))

    return unmatched, used_markers


def test_static_copies_have_no_unexplained_differences():
    """Every difference between static/ and docker-server/static/ must be on
    the allow-list above, or the build should refuse to stay green.

    This is the divergence budget: an inventory found 245 differing lines
    between the two copies, almost all deliberate. Two were not, and both
    shipped before anyone noticed -- the two tests above now pin those. This
    test is the general case: it does not know what the "right" content of
    either copy is, only that a change nobody explained is exactly the kind of
    thing that produced those two bugs.
    """
    unmatched, _ = _classify_differences()
    if not unmatched:
        return

    parts = [
        "Found a difference between static/ and docker-server/static/ that is "
        "not on ALLOWED_DIFFERENCES in tests/test_ui_copies.py.\n"
        "If this is deliberate, add an entry (file, category, marker, reason). "
        "If it is not, that is the drift this test exists to catch.\n"
    ]
    for filename, hunk in unmatched:
        parts.append(f"--- unexplained hunk in {filename} ---\n{hunk}")
    pytest.fail("\n".join(parts), pytrace=False)


def test_allowed_differences_list_has_no_stale_entries():
    """Every entry in ALLOWED_DIFFERENCES must still match a real difference.

    An entry that matches nothing means one of two things: the copies were
    quietly resynced on that point (fine, but the entry is now dead
    documentation and should go), or a deliberate divergence got reverted by
    accident (not fine, and worth exactly the same red build as an unexplained
    difference). Either way, the person who caused it is looking at the diff
    right now, which is the cheapest moment to ask.
    """
    _, used_markers = _classify_differences()
    stale = [
        entry
        for entry in ALLOWED_DIFFERENCES
        if (entry.file, entry.marker) not in used_markers
    ]
    if not stale:
        return

    parts = [
        "Entries in ALLOWED_DIFFERENCES (tests/test_ui_copies.py) that no "
        "longer match any difference between static/ and docker-server/static/. "
        "Either the copies converged on this point (delete the entry) or a "
        "deliberate divergence was reverted (restore it):\n"
    ]
    for entry in stale:
        parts.append(
            f"  {entry.file}: [{entry.category}] marker={entry.marker!r}\n"
            f"    {entry.reason}"
        )
    pytest.fail("\n".join(parts), pytrace=False)


# Assets with zero allowed differences: any drift here is unconditionally a bug,
# so there is no allow-list to maintain -- just byte-for-byte equality. Kept
# separate from ALLOWED_DIFFERENCES rather than modeled as "zero markers
# allowed", since these files are identical today and the interesting failure
# mode is "someone edited one copy", not "someone edited both copies the same
# unexplained way".
IDENTICAL_ASSETS = (
    "manifest.json",
    "privacy.html",
    "apple-touch-icon.png",
    "icon-192.png",
    "icon-512.png",
)


def test_assets_with_no_allowed_differences_stay_identical():
    """manifest.json, privacy.html and the three icons are byte-identical today
    and carry no allow-list entry, so any difference here is a straightforward
    bug: someone edited one copy and not the other of a file that was never
    supposed to diverge.
    """
    mismatched = []
    for filename in IDENTICAL_ASSETS:
        desktop_bytes = (STATIC_DIR / filename).read_bytes()
        server_bytes = (SERVER_DIR / filename).read_bytes()
        if desktop_bytes != server_bytes:
            mismatched.append(filename)

    assert not mismatched, (
        f"{mismatched} differ between static/ and docker-server/static/ but "
        "have no allow-list entry and no reason to diverge. If the difference "
        "is deliberate, give it an ALLOWED_DIFFERENCES-style entry instead of "
        "leaving it unexplained; if not, one copy needs the other's fix."
    )
