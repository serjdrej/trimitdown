# Contributing to TrimItDown

Thanks for your interest! Bug reports, feature ideas, and pull requests are all welcome.

## Reporting bugs / requesting features

Open an [issue](https://github.com/serjdrej/trimitdown/issues) using the matching template.
For PDF conversion problems, attaching the problematic PDF (or a redacted fragment of it)
makes a fix dramatically more likely.

## Development setup

```bash
git clone https://github.com/serjdrej/trimitdown.git
cd trimitdown
python -m venv venv
venv/Scripts/activate        # Windows; on macOS/Linux: source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn server_app:app --port 8000   # web UI at http://localhost:8000
```

Run the tests with:

```bash
python -m pytest
```

[DEVELOPMENT.md](DEVELOPMENT.md) covers the desktop app internals (pywebview shell,
PyInstaller packaging, known build gotchas). The Docker server lives in
[`docker-server/`](docker-server/) and shares its conversion core with the desktop apps
via [`core/`](core/).

## Pull requests

- Keep PRs focused — one change per PR.
- Make sure `python -m pytest` passes; changes to the PDF engine
  ([`core/pdf_extract.py`](core/pdf_extract.py)) are guarded by the labeled table-detection
  suite in [`tests/`](tests/).
- User-facing UI strings must exist in **both Russian and English** (see the `STRINGS`
  dictionaries in `static/app.js` / `docker-server/static/app.js`).
