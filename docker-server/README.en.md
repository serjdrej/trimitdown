*Read in: [русский](README.md) · English (this file)*

# TrimItDown Docker service

FastAPI + [MarkItDown](https://github.com/microsoft/markitdown) on Docker: convert files to
Markdown, a searchable archive with delete support, HTTPS with a self-signed certificate. The
same service also serves a PWA — on iPhone it opens like a regular site and installs to the
Home Screen as a full app (offline UI caching via a service worker, its own icon).

Runs on any machine with Docker — a home NAS, a VPS, your own server. The folder is called
`docker-server/` because it works for any Docker-capable server, not just a NAS.

This repository does not publish a ready-made Docker image. This deployment builds a chosen source
release and requires Git, Docker with Compose, and OpenSSL. Clone into a separate directory, not
inside an existing clone, to avoid nesting `trimitdown/docker-server/trimitdown/docker-server`.

## Deploy

```bash
git clone https://github.com/serjdrej/trimitdown.git && cd trimitdown && git checkout <release-tag> && cd docker-server
./setup.sh YOUR_SERVER_ADDRESS
docker compose up -d --build      # Compose v1: docker-compose up -d --build
```

`setup.sh` prints the first-visit link. It is stored in a cookie for later visits.

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

## PWA on iPhone/iPad

For the full pitch on the iOS PWA (what it gets you, what it looks like) see the
[root README](../README.md#get-it). This file only covers the technical
side: certificate trust (above) and the API (below).

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/convert` | Converts the uploaded file, saves it to the archive, returns the markdown |
| `GET` | `/api/archive?q=` | Lists the archive (optional name search) |
| `GET` | `/api/archive/{filename}` | Download a file. `?raw=1` → `application/octet-stream` for desktop apps; no param → `text/markdown` for browsers |
| `DELETE` | `/api/archive/{filename}` | Deletes a file from the archive |
| `GET` | `/cert` | Serves the public certificate for installing on a device |

The project declares the narrower MarkItDown extras
`docx,pdf,pptx,xlsx,xls,outlook`, rather than `markitdown[all]`.
