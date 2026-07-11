*Read in: [русский](README.md) · English (this file)*

# MarkItDown — file-to-Markdown converter for iPhone, Windows, and Mac

**MarkItDown** turns any file — PDF, Word (docx), PowerPoint (pptx), Excel (xlsx/xls), an
Outlook `.msg` message — into clean, readable Markdown with none of the formatting mess. It
works as an iPhone app (installed straight from Safari, no App Store), as a portable Windows
program, and as a Mac app — with one shared archive of converted files across every device.

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
| iPhone / iPad (PWA) + Docker server | [`nas-server/`](nas-server/) | Installs straight from Safari, no App Store — details below |
| Windows | repo root | `MarkItDown-windows-x64.exe` from [Releases](../../releases) — portable, no install needed |
| macOS (Intel and Apple Silicon) | repo root | `.zip` from [Releases](../../releases), pick the archive matching your chip |

## The iPhone/iPad app — no App Store required

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
[`nas-server/README.en.md`](nas-server/README.en.md).

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

- **`nas-server/`** — the Docker service (`Dockerfile`, `docker-compose.yaml`, `app.py`,
  `static/` — the same HTML/CSS/JS you see on iPhone as a PWA). See
  [`nas-server/README.en.md`](nas-server/README.en.md).
- **`main.py`** — desktop app entry point: server-reachability check, local server, pywebview window.
- **`server_app.py`** — the FastAPI app used in the desktop apps' local (offline) mode.
- **`static/`** — desktop app frontend (same UI, plus a server/local mode badge).
- **`main.spec`** — PyInstaller spec for macOS.
- **`mac-build/AppIcon.iconset/`**, **`icon.ico`** — the "M↓" icon for every platform.
- **`.github/workflows/build-macos.yml`** — CI that builds `.app` bundles for arm64 and x86_64
  on every push to `main`.
- **`DEVELOPMENT.md`** — desktop app internals for development: how to iterate without
  rebuilding the `.app` on every change, and the full history of bugs we hit and fixed.

## Limitations

- The server's self-signed HTTPS certificate needs a one-time manual trust on every device
  (iOS: install the profile and enable full trust in Settings; Windows: import into
  `CurrentUser\Root`; macOS: Keychain Access → "Always Trust").
- The apps aren't signed with a developer certificate (Apple or Microsoft) — first launch
  needs a one-time override (macOS: right-click → Open; Windows: SmartScreen, if it appears).
- The server's IP is hardcoded in `main.py` (`NAS_URL`) — update it there if the server moves.
