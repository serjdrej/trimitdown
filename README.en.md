*Read in: [русский](README.md) · English (this file)*

# MarkItDown — personal file-to-Markdown toolkit

A wrapper around [MarkItDown](https://github.com/microsoft/markitdown) (any file — pdf, docx,
pptx, xlsx, images, and more — into clean Markdown) across three platforms, with a shared
archive of converted files across all your devices.

## Platforms

| Platform | Folder | How to get it |
|---|---|---|
| Docker server + PWA for iOS | [`nas-server/`](nas-server/) | `docker-compose up -d --build` on any machine running Docker (NAS, VPS, home server) |
| Windows | repo root | `MarkItDown-windows-x64.exe` from [Releases](../../releases) — portable, no install needed |
| macOS (Intel and Apple Silicon) | repo root | `.zip` from [Releases](../../releases), pick the archive matching your chip |

The folder is called `nas-server/` for historical reasons (it originally ran on a home NAS) —
it's a plain Docker container and runs on any machine with Docker (your own server, a VPS,
anything).

## How it works

- **The Docker server is the source of truth.** A FastAPI service on Docker with HTTPS
  (self-signed certificate); the archive lives on the server itself. The same service also
  serves a PWA — on iPhone it opens like a regular site and installs to the Home Screen.
- **The Windows/macOS apps** check at startup whether the server is reachable:
  - reachable → open the window straight on the server, archive shared across every device;
  - unreachable → spin up a bundled local server and work fully offline, archive stored next
    to the app.
- The desktop app shell is [pywebview](https://pywebview.flowrl.com/)
  (Windows: WebView2, macOS: WKWebView), packaged as a single file with PyInstaller.

## Repository layout

- **`nas-server/`** — the Docker service (`Dockerfile`, `docker-compose.yaml`, `app.py`,
  `static/` — the same HTML/CSS/JS you see on iPhone as a PWA). See
  [`nas-server/README.en.md`](nas-server/README.en.md).
- **`main.py`** — desktop app entry point: server-reachability check, local server, pywebview window.
- **`server_app.py`** — the FastAPI app used in the desktop apps' local (offline) mode.
- **`static/`** — desktop app frontend (same UI, plus a server/local mode badge).
- **`main.spec`** — PyInstaller spec for macOS (`--onedir`, ATS exception in `Info.plist` —
  see "Known gotchas" below).
- **`mac-build/AppIcon.iconset/`**, **`icon.ico`** — the "M↓" icon for every platform.
- **`.github/workflows/build-macos.yml`** — CI that builds `.app` bundles for arm64 and x86_64
  on every push to `main`.
- **`DEVELOPMENT.md`** — desktop app internals: how to iterate without rebuilding the `.app`
  on every change, and the full history of bugs we hit and fixed.

## Known gotchas (already fixed, kept here as documentation)

Both platforms hit the same `/api/archive/{filename}` endpoint on the server, but need
different download behavior — found and fixed empirically:

- **WKWebView (macOS) and WebView2 (Windows) decide render-vs-download by whether they can
  display the MIME type inline, ignoring `Content-Disposition`.** Because of this, opening a
  file from a desktop app rendered it right in the window instead of saving it to disk.
- **iOS Safari, conversely, falls back to sniffing the raw bytes when the MIME type is
  `application/octet-stream`** to guess a type for its preview — and sometimes misdetects
  plain markdown text as HTML.

The fix: tell the two client types apart at request time via `window.pywebview` (an object
pywebview automatically injects into every page it loads; a real browser never has it).
pywebview clients request `/api/archive/{filename}?raw=1` and get back
`application/octet-stream`; regular browsers get `text/markdown` with no query param. Code is
in [`nas-server/app.py`](nas-server/app.py) and
[`nas-server/static/app.js`](nas-server/static/app.js).

One more wrinkle — the macOS build **must be `--onedir`, not `--onefile`**: PyInstaller
re-extracts a `--onefile` bundle on every launch, and on a slower machine that blew past the
timeout for the local server to come up. Details in `DEVELOPMENT.md`.

## Limitations

- The server's self-signed HTTPS certificate needs a one-time manual trust on every device
  (iOS: install the profile and enable full trust in Settings; Windows: import into
  `CurrentUser\Root`; macOS: Keychain Access → "Always Trust").
- The apps aren't signed with a developer certificate (Apple or Microsoft) — first launch
  needs a one-time override (macOS: right-click → Open; Windows: SmartScreen, if it appears).
- The server's IP is hardcoded in `main.py` (`NAS_URL`) — update it there if the server moves.
