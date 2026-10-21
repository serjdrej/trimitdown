<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="brand/wordmark_dark.svg">
  <img src="brand/wordmark_light.svg" alt="TrimItDown" width="360">
</picture>

**Documents → LLM-ready Markdown. PDFs checked page by page, scans handed to review.**

*Read this in: English (this file) · [русский](README.ru.md)*

[![PyPI](https://img.shields.io/pypi/v/trimitdown?label=trimitdown&color=3775A9)](https://pypi.org/project/trimitdown/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

`trimitdown` turns PDF, Word (docx, doc, rtf), PowerPoint (pptx), Excel (xlsx/xls), HTML and
plain text into Markdown meant to be pasted into an LLM or read by an agent. The objective is the
fewest tokens with the information preserved: a real table becomes a Markdown table, a page
whose text cannot be trusted says so instead of passing as text.

It is a command-line tool and a Python library, and it works offline. Since 0.2.0 this package
is the whole product; see [Earlier releases](#earlier-releases) for the desktop app and the
Docker server.

## Install

Requires Python 3.10+.

```bash
uv tool install trimitdown     # or: pipx install trimitdown
uvx trimitdown convert report.pdf   # once, without installing
```

A plain `pip install` into the system Python is refused on many distributions and on Homebrew
(PEP 668); the commands above put the package in an isolated environment. Inside your own
virtual environment, `pip install trimitdown` is fine.

PDF needs nothing more. Word (docx, doc, rtf), PowerPoint, Excel, OpenDocument, EPUB, CSV and
HTML need the `office` extra:

```bash
uv tool install "trimitdown[office]"     # or: pip install "trimitdown[office]"
```

The extra installs on Python 3.15 as well: it is [firecrawl-anydoc](https://pypi.org/project/firecrawl-anydoc/)
(one wheel, no dependencies of its own) and [markdownify](https://pypi.org/project/markdownify/).
Without the extra, converting an office file fails with a message naming the extra. Plain text
(`.txt`, `.md`) needs no extra.

## Convert

```bash
trimitdown convert report.pdf -o report.md
trimitdown convert report.pdf --page-anchors -o report.md   # each page starts with <!-- page N -->
trimitdown convert - --type pdf < report.pdf     # from a stream
```

Without `-o`, Markdown goes to standard output.

```python
from trimitdown.convert import convert_path

result = convert_path("report.pdf")
result.text            # the Markdown
result.pages           # PDFs: how each page was routed, and why
result.tokens_after    # cl100k tokens of the Markdown
```

Non-PDF formats: `.docx`, `.doc`, `.rtf`, `.odt`, `.epub`, `.xlsx`, `.xls`, `.ods`, `.csv`,
`.pptx`, `.ppt`, `.odp` go through firecrawl-anydoc; `.html`/`.htm` (and files whose content is
HTML whatever the name) through markdownify, without scripts and styles; `.txt` and `.md` pass
through unchanged, as UTF-8. Outlook `.msg`, JSON, XML, ZIP, images and audio are not converted
(0.3.0 dropped them); the converter refuses them with a message instead of returning nothing.
Documents are never sent anywhere: scanned pages in an office file are refused, not OCR-ed in a
cloud.

## How PDFs are handled

PDFs go through [pdf-inspector](https://pypi.org/project/pdf-inspector/), which gave the best
structure in our measurements (headings, tables with and without rules) and the fewest tokens.
It also loses text without saying so — whole pages come back empty while their text layer is
intact, and on some pages Cyrillic comes back as Latin with no warning. So every page is checked
against an independent decoder ([pypdf](https://pypi.org/project/pypdf/)) and takes one of five
paths:

| Path | When | What the page contributes |
|---|---|---|
| `accept` | pdf-inspector read the page | its Markdown, unchanged |
| `substitute` | pdf-inspector lost text the layer still has | the text layer as plain text |
| `scan` | no text layer, or an OCR layer under a page image | a marker, or the OCR layer with a note that it is unverified |
| `corrupt` | a text layer every decoder reads as garbage | a marker |
| `blank` | no text layer and nothing on the page | nothing |

The loss check is counted per script (Cyrillic, Latin, Greek, CJK…), so a page where one
alphabet silently replaced another is caught even though the number of letters did not change.

Markers look like this, one line each:

```
[trimitdown: page 12 has no usable text layer (scan)]
[trimitdown: page 14: OCR layer, not verified]
```

When any page did not come from pdf-inspector, `convert` prints one line to standard error, for
example `7 pages: 1 accept, 2 substitute, 2 scan, 1 corrupt, 1 blank; 3 need review`. A clean
document converts silently.

## Review: scans and unreadable pages

`trimitdown` does not do OCR itself and does not review anything. It prepares the pages that
need a look for an agent (or a person) who does:

```bash
trimitdown convert scan.pdf --review-dir out/
```

writes

| | |
|---|---|
| `out/document.md` | the converted document, with a `<!-- page N -->` anchor before each page |
| `out/manifest.json` | every page: its path and reasons, image, candidate text, OCR status, metrics |
| `out/REVIEW.md` | the review procedure: OCR first, then compare with the image and correct only the differences |
| `out/pages/pNNNN.png` | an image of each page to review (the source scan when it is the whole page, otherwise a 300 dpi render) |
| `out/candidates/pNNNN.txt` | the text to start from: the PDF's own OCR layer, or fresh Tesseract output; empty if there is none |
| `out/reviewed/` | where the reviewer writes |

[Tesseract](https://github.com/tesseract-ocr/tesseract) is optional and external. It is looked
for in `--tesseract`, `TRIMITDOWN_TESSERACT`, `PATH`, then the usual install locations; the
defaults are the measured ones (`-l rus --psm 3`, orientation from `--psm 0`), changed with
`--ocr-lang` and `--tessdata-dir`. Without Tesseract, or without the language data, pages still
go to review with an empty candidate, and the manifest and standard error say why.

Other options: `--ocr-fresh` (OCR scans that already carry an OCR layer), `--no-ocr`,
`--review-substitute` (send `substitute` pages too), `--review-markers ru|en` (the marks the
procedure asks for: `[неразборчиво]`, `=== стр. N ===` by default, or `[illegible]`,
`=== page N ===`).

When the review is done:

```bash
trimitdown assemble out/ -o report.md
```

puts each reviewed page in place of its marker. It reads `reviewed/doc.txt` with one
`=== стр. N ===` (or `=== page N ===`) header per page, or one `reviewed/pNNNN.txt` per page,
and refuses a page reviewed twice, a page that does not exist or text for a page that was not
sent for review (a bare header for such a page is ignored). The result keeps `<!-- page N -->` at
the start of every page, so it can be cited by page; `--no-page-anchors` drops it.

Readable text in a text layer does not prove its digits right. For the pages that were not
sent, `trimitdown render report.pdf --pages 5,7 -o img/` writes page images to check them
against.

From Python: `trimitdown.review.prepare_review`, `assemble` and `render_pages`.

## Limitations

- No built-in OCR, and no review performed by the program: scans need Tesseract and a reviewer.
- A loss of Latin letters alone is not checked. On the 200-document benchmark the Latin check
  replaced good structured Markdown (headings) with plain text more often than it recovered
  text, so it ships switched off (`GATE_LATIN` in `text_metrics.py`). Cyrillic replaced by
  Latin is still caught: that is a loss of Cyrillic.
- Text under an image (an OCR layer of a different shape, or text an overlay was meant to hide)
  is accepted as text; the review manifest records how much of each page is under images.
- The garbage detector behind `corrupt` raised no false alarm on 2,795 real pages, but how
  well it catches a genuinely broken text layer has not been measured: no such page was in
  the test corpora.
- Slower than pdf-inspector alone, because every page is also decoded by pypdf to catch a
  silent loss. On 180 pages of Russian tax forms the route took 62 s against 5.6 s; on the
  200-document benchmark, 48 ms per document against 7. pdfium as the second decoder makes the
  same decisions on every real page measured and is about five times faster, but it shares
  pdf-inspector's blind spot on text carried by `ActualText`, so it is not used.
- Password-protected PDFs are refused.

## Earlier releases

Up to 0.1.2 TrimItDown also shipped a desktop app for Windows and macOS, a self-hosted Docker
server with an iPhone PWA, and a Scoop manifest. They are no longer released. Their last builds
are attached to [v0.1.2](https://github.com/serjdrej/trimitdown/releases/tag/v0.1.2), the Scoop
bucket in this repository stays pointed at it, and the code remains in the tree — see
[DEVELOPMENT.md](DEVELOPMENT.md). The PDF engine they use, `trimitdown-pdf`, is described in
[docs/pdf-engine.md](docs/pdf-engine.md); this package no longer depends on it.

## Repository layout

- [`src/trimitdown/`](src/trimitdown/) — the package: conversion, the PDF route, review
- [`tests/`](tests/) — the portable suite, on synthetic PDFs built in the tests
- [`packages/trimitdown-pdf/`](packages/trimitdown-pdf/), [`core/`](core/),
  [`docker-server/`](docker-server/), [`static/`](static/), [`main.py`](main.py) — the earlier
  desktop and server applications and their engine

## Contributing

Bug reports and PRs are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and
[DEVELOPMENT.md](DEVELOPMENT.md).

## License and credits

Code is [MIT](LICENSE). PDFs are read with [pdf-inspector](https://pypi.org/project/pdf-inspector/)
(MIT), [pypdf](https://pypi.org/project/pypdf/) (BSD) and
[pypdfium2](https://pypi.org/project/pypdfium2/) (Apache-2.0 / BSD, with PDFium); other formats
with [firecrawl-anydoc](https://pypi.org/project/firecrawl-anydoc/) (MIT) and
[markdownify](https://pypi.org/project/markdownify/) (MIT). See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
