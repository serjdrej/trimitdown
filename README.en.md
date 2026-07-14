*Read in: [русский](README.md) · English (this file)*

# TrimItDown — file-to-Markdown converter for iPhone, Windows, and Mac

*A mobile app, Windows/Mac programs, and a Docker server, built on top of the open-source
[MarkItDown](https://github.com/microsoft/markitdown) library by Microsoft — an open-source
file-to-Markdown conversion engine.*

Any file — PDF, Word (docx), PowerPoint (pptx), Excel (xlsx/xls), an Outlook `.msg` message —
turns into clean, readable Markdown with none of the formatting mess. It works as an iPhone app
(installed straight from Safari, no App Store), as a portable Windows program, and as a Mac app
— with one shared archive of converted files across every device.

## Why you'd want this

- **Got a PDF, Word, or PowerPoint file and want the text in your notes, ChatGPT/Claude, or
  your own markdown vault** (Obsidian, Notion, etc.) — without the broken formatting that
  usually survives copy-paste. Just convert the file, get clean text back.
- **Works without the internet and without anyone else's cloud.** Conversion happens on a
  server you run yourself (or right on your computer in offline mode) — files never go to a
  third-party SaaS, and there's no per-conversion fee.
- **One archive, every device.** Convert a file on your phone — it's already there on your
  computer, and the other way around.

## Platforms

| Platform | Folder | How to get it |
|---|---|---|
| iPhone / iPad (PWA) + Docker server | [`docker-server/`](docker-server/) | Installs straight from Safari, no App Store — details below |
| Windows | repo root | `TrimItDown-windows-x64.exe` from [Releases](../../releases) — portable, no install needed |
| macOS (Intel and Apple Silicon) | repo root | `.zip` from [Releases](../../releases), pick the archive matching your chip |

## The iPhone and iPad app

The Docker server (see below) serves a progressive web app (PWA): a full mobile app for
converting files to Markdown on iOS that installs to the Home Screen straight from Safari — no
App Store, no Apple Developer account, no app review.

What that gets you in practice:

- **A screen that looks like a regular App Store app.** Once installed, it opens in full-screen
  mode — no Safari address bar, its own icon on the Home Screen, and a status-bar color matching
  the app's theme. Indistinguishable from a native app at a glance.
- **Your own server, not someone else's cloud.** Files go to a server you run yourself (home
  NAS, a VPS, any machine with Docker) — no third-party SaaS, no per-conversion fees, your data
  never leaves your own infrastructure.
- **The same conversion engine as the desktop apps.**
  [MarkItDown](https://github.com/microsoft/markitdown) turns docx, pdf, pptx, xlsx, xls,
  Outlook `.msg` files and more into clean, readable markdown right on your phone — receive a
  file, share it into the app, get markdown back.
- **A searchable archive shared across every device.** Every conversion is saved on the server
  and visible from any device that connects to it — iPhone, iPad, Mac, a Windows computer.
- **Works even on a flaky connection.** The interface is cached on the device, so the app opens
  instantly — actual file conversion still needs the server reachable, of course.
- **Interface in Russian and English** — detected automatically from the device's system
  language, no manual switch needed.

One one-time setup step: before the first install you need to approve your server's HTTPS
certificate once (otherwise Safari shows an untrusted-connection warning) — full instructions in
[`docker-server/README.en.md`](docker-server/README.en.md).

## How it works

- **The Docker server is the source of truth.** A service on Docker with HTTPS; the archive
  lives on the server itself. The same service also serves the PWA for iPhone (see above).
- **The Windows/macOS apps** check at startup whether the server is reachable:
  - reachable → open the window straight on the server, archive shared across every device;
  - unreachable → spin up a bundled local server and work fully offline, archive stored next
    to the app.
- The desktop app shell is [pywebview](https://pywebview.flowrl.com/)
  (Windows: WebView2, macOS: WKWebView), packaged as a single file with PyInstaller.

## Repository layout

- **`core/converter.py`** — shared, platform-agnostic conversion/archive logic (safe_stem,
  MarkItDown conversion, listing/deleting files). Both `docker-server/app.py` and `server_app.py`
  build on top of it.
- **`docker-server/`** — the Docker service (`Dockerfile`, `docker-compose.yaml`, `app.py`,
  `static/` — the same HTML/CSS/JS you see on iPhone as a PWA). See
  [`docker-server/README.en.md`](docker-server/README.en.md).
- **`main.py`** — desktop app entry point: server-reachability check, local server, pywebview window.
- **`server_app.py`** — a thin wrapper around `core/converter.py` for the desktop apps' local
  (offline) mode (archive/static paths are platform-specific; the actual logic is shared).
- **`static/`** — desktop app frontend (same UI, plus a server/local mode badge).
- **`main.spec`** — PyInstaller spec for macOS.
- **`mac-build/AppIcon.iconset/`**, **`icon.ico`** — the "M↓" icon for every platform.
- **`.github/workflows/build-macos.yml`** — CI that builds `.app` bundles for arm64 and x86_64
  on every push to `main`.
- **`DEVELOPMENT.md`** — desktop app internals for development: how to iterate without
  rebuilding the `.app` on every change, and the full history of bugs we hit and fixed.

## License and credits

All the actual file-conversion logic is [MarkItDown](https://github.com/microsoft/markitdown) by
Microsoft (MIT licensed). The compiled binaries (Windows exe, macOS `.app`) bundle that package
and its dependencies in full — the complete license text is in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This repository's own code (the wrapper, desktop apps, Docker service) is
[MIT licensed](LICENSE).

## Pointing the Windows/macOS apps at your own server

By default the app runs fully offline — no setup needed. To connect it to your own Docker
server (see `docker-server/`) and get a shared archive across devices: launch the app once (a
`config.json` appears next to the exe/`.app`), close it, and fill in your server's address:

```json
{ "server_url": "https://YOUR_IP_OR_DOMAIN:8002" }
```

On the next launch the app tries that address — if it's reachable, it opens in server mode with
the shared archive; if not (server off, not on the network, etc.), it silently falls back to
offline mode, no need to undo anything.

## Limitations

- The server's self-signed HTTPS certificate needs a one-time manual trust on every device
  (iOS: install the profile and enable full trust in Settings; Windows: import into
  `CurrentUser\Root`; macOS: Keychain Access → "Always Trust").
- The apps aren't signed with a developer certificate (Apple or Microsoft) — first launch
  needs a one-time override (macOS: right-click → Open; Windows: SmartScreen, if it appears).
