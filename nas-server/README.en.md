*Read in: [русский](README.md) · English (this file)*

# MarkItDown Docker service

FastAPI + [MarkItDown](https://github.com/microsoft/markitdown) on Docker: convert files to
Markdown, a searchable archive with delete support, HTTPS with a self-signed certificate. The
same service also serves a PWA — on iPhone it opens like a regular site and installs to the
Home Screen as a full app (offline UI caching via a service worker, its own icon).

Runs on any machine with Docker — a home NAS, a VPS, your own server. The folder is called
`nas-server/` for historical reasons (it originally ran on a NAS), but nothing in the code is
NAS-specific.

## Deploy

```bash
# on whichever machine will run the service (NAS, VPS, your own server — anything with Docker)
mkdir -p certs archive
cd certs
openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout key.pem -out cert.pem -days 3650 \
  -subj "/CN=markitdown-nas" \
  -addext "subjectAltName=IP:YOUR_SERVER_IP"
cd ..
sudo docker-compose up -d --build
```

`docker-compose.yaml` maps `8002:8000`, mounts `./archive` (the converted-files archive) and
`./certs:/certs:ro` (the certificate). Change the port/IP in the same file.

## Installing the certificate on your devices

The self-signed certificate needs a one-time approval on each device — otherwise you'll get an
untrusted-connection warning (and on the desktop apps, the server mode silently fails with no
error shown in the UI at all):

- **iOS**: open `https://YOUR_IP:8002/cert` in Safari → download the profile → Settings →
  install it → Settings → General → About → Certificate Trust Settings → enable full trust.
  After that: `https://YOUR_IP:8002` → Share → "Add to Home Screen".
- **Windows**: download `/cert`, `certutil -user -addstore "Root" cert.pem`.
- **macOS**: download `/cert`, open it in Keychain Access → "Always Trust".

## PWA on iPhone/iPad — install without the App Store

The same Docker service serves a progressive web app (PWA): a full mobile app for converting
files to Markdown on iOS that installs to the Home Screen straight from Safari — no App Store,
no Apple Developer account, no review process.

What that gets you in practice:

- **A screen that looks native.** Once installed, it opens in full-screen standalone mode — no
  Safari address bar, its own "M↓" icon on the Home Screen, and a status-bar color matching the
  app's theme. Indistinguishable from an App Store app at a glance.
- **Your own server, not someone else's cloud.** Files go to a server you run yourself (home
  NAS, VPS, whatever) — no third-party SaaS, no per-conversion fees, your data never leaves
  your own infrastructure.
- **The same conversion engine as the desktop apps.**
  [MarkItDown](https://github.com/microsoft/markitdown) turns docx, pdf, pptx, xlsx, xls,
  Outlook `.msg` files and more into clean, readable markdown right on your phone — receive or
  photograph a file, share it into the app, get markdown back.
- **A searchable archive shared across every device.** Every conversion is saved on the server
  and visible from any device that connects to it — iPhone, iPad, Mac, a Windows laptop.
- **Offline UI caching.** A service worker caches the HTML/CSS/JS shell, so the app opens
  instantly even on a flaky connection (actual conversion still needs the server reachable —
  only the interface is cached, not the backend).
- **Interface in Russian and English** — detected automatically from the device's system
  language, no manual switch needed.

One limitation: before the first install you need to approve the server's self-signed HTTPS
certificate once (see the section above) — without that, Safari shows an untrusted-connection
warning. It's a one-time per-device setup, not something you repeat on every launch.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/convert` | Converts the uploaded file, saves it to the archive, returns the markdown |
| `GET` | `/api/archive?q=` | Lists the archive (optional name search) |
| `GET` | `/api/archive/{filename}` | Download a file. `?raw=1` → `application/octet-stream` for desktop apps (see the root README's "Known gotchas" section); no param → `text/markdown` for browsers |
| `DELETE` | `/api/archive/{filename}` | Deletes a file from the archive |
| `GET` | `/cert` | Serves the public certificate for installing on a device |

`markitdown[all]` pulls in heavy ML dependencies (audio transcription, etc.) — a deliberate
choice for the server version, where disk space and build time aren't a constraint. The desktop
version (see repo root) trims the extras for a portable build.
