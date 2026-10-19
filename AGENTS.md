# Working in this repository

Instructions for any AI agent working here — Codex, Claude Code, or anything
else. Read this before touching code. Human contributors want
[CONTRIBUTING.md](CONTRIBUTING.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

## What this project is

TrimItDown converts documents to markdown meant to be pasted into an LLM. The
objective function is **fewest output tokens with the information preserved** —
not visual fidelity to the original page. That distinction settles most
trade-offs: a real table rendered as a markdown table is worth its tokens, a
table hallucinated out of prose is not.

One artifact comes out of this tree:

| Artifact | Built from | Delivered by |
|---|---|---|
| `trimitdown` (wheel/sdist) | `src/trimitdown/` | PyPI → `uvx` / `pip` |

It is the extractor the owner's skills use: a CLI and a Python API. The desktop
app (PyInstaller over the flat root modules) and the server image
(`docker-server/`) are **code in the tree that is no longer released** (owner's
decision, 2026-10-19). Their workflows run on request only; do not delete them,
and do not re-enable their triggers without the owner.

## Layering — the rule that shapes the code

`src/trimitdown/convert.py` is **pure**: a path or bytes in, text and token
counts out. It must never import FastAPI. The HTTP layer lives in
`core/converter.py` and calls into it. The PDF route it calls,
`pdf_route.py` (with `text_metrics.py`), is pure in the same sense.
`review.py` writes directories and starts Tesseract; `convert.py` does not
import it.

This is enforced by a test, not by good intentions:
`tests/test_convert_pure.py::test_pure_module_does_not_import_fastapi`. Breaking
it costs the CLI package the entire web stack while breaking nothing visible —
which is why it is a test and not a comment. `tests/test_review.py` holds the
same line for the review path.

## Invariants

- **`pytest -m "not corpus"` must pass with zero skips.** Not "zero failures" —
  zero *skips*. A silently skipped test in a green run is a failure mode this
  project has hit repeatedly, and `tests.yml` asserts the count.
- **CI runs on `ubuntu-latest`** across Python 3.10 / 3.12 / 3.13. A
  Windows-only import in a test turns CI red. `msvcrt`, `winreg` and friends are
  out, and a `skipif` to paper over them violates the zero-skips invariant.
- **The package version literal appears in exactly one file**:
  `src/trimitdown/__init__.py`. Everything else imports it. A second copy will
  disagree with the first eventually.
- **Published text is English unless it is deliberately bilingual.** Commit
  messages, workflow step names, the comments inside `run:` blocks (Actions
  echoes them into a public log), issue and PR text: English. Bilingual where
  that was chosen on purpose and stays chosen — release notes, the README pair,
  the desktop UI. If you are about to invent a language rule for a new kind of
  text, it is English. Written down after eighteen Russian commit messages
  reached `main` and surfaced as run titles in Actions. The review rule
  (`src/trimitdown/review_rule.md`) is English; the review *marks* it asks for
  are Russian by default (`--review-markers ru`), because the owner's skills and
  their quote checker read them — that is a chosen exception, not a precedent.
- **pdf-inspector is pinned exactly** (`pdf-inspector==1.25.2`). The route keys
  on its reason identifiers, which upstream does not document. Raising the pin
  is its own commit, after the corpus measurements in `RELEASING.md`; the weekly
  `pdf-inspector-latest.yml` only says that a new version exists.
- **`packages/trimitdown-pdf/` is frozen.** It is published to PyPI and pinned
  exactly; the package no longer depends on it, the desktop and server code
  still do. Bug fixes are allowed; new algorithmic work is not, without the
  owner's agreement.
- **Corpus-derived data, personal data and internal documents never enter this
  tree.** They live outside it. Counts and timings may be published; filenames,
  paths and document text may not.

## The pre-commit guard

A PII guard runs on commit. Install it once per clone:

```bash
git config core.hooksPath .githooks
```

**Never bypass it.** No `--no-verify`, no editing the pattern list to make your
commit pass. It exists because personal data once reached this repository in
public, and the cost of that is not hypothetical.

It is deliberately broad, and it matches prose *about* a forbidden string as
readily as the string itself — including a comment explaining why you removed
one. If it rejects a legitimate line, **reword the line**. Narrowing a pattern
needs the owner's agreement; there is a note in `.githooks/pre-commit` recording
the last time this came up and how it was settled.

## Testing

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -m "not corpus"        # the portable suite: synthetic PDFs, no corpus
```

Corpus tests are marked `corpus` and need documents this repository does not
ship. They are deselected by default and are the owner's pre-release gate.

**On writing tests here:** a test that passes on broken code is worse than no
test, because it buys false confidence. Several tests in this suite were
tightened only after someone deliberately reintroduced the bug and watched them
stay green. When you add a test for a defect, break the fix and confirm the test
fails before you commit it — and say in the test's comment what it would miss if
weakened.

## Silent failures to watch for

This codebase has been bitten by the same shape more than once: a mechanism that
fails without saying so.

- PyInstaller does not error on a missing `datas` path. It ships a bundle
  without the file, and the failure appears at a user's first run.
- `tiktoken` does not fail on a missing cache. It downloads over the network,
  so the defect is invisible to anyone with connectivity — including every CI
  runner.
- `markitdown` dispatches on file content, not extension. A file misnamed
  `.pdf` still converts; a routing check that assumes otherwise breaks it.
- The PDF signature check has been written wrong twice: once as a 5-byte slice
  against a 4-byte literal, once anchored at byte 0 when real files carry the
  marker at an offset. It scans a window for a reason.
- pdf-inspector returns an empty page, or a page in the wrong alphabet, with
  no error and sometimes no flag. That is why every page is checked against
  pypdf (`pdf_route.py`); a change that skips the check on unflagged pages
  brings the silent loss back.
- Tesseract can be missing, can lack the `rus` or `osd` data, or can sit
  outside `PATH` (the Windows installer does that). None of these may be worked
  around quietly: the page still goes to review, the manifest and stderr say
  why, and recognition never falls back to `eng`, which turns Cyrillic into
  confident garbage. CI has no Tesseract; tests use a fake one, never a skip.
- `uv pip compile` takes the first Python on `PATH` as the lock's floor. With
  3.15 first it found no onnxruntime wheel and backtracked markitdown to 0.0.2
  without an error. `scripts/compile-locks.sh` names `--python-version` for
  that reason.

When you touch any of these, assert the outcome — not the absence of an error.

## Commits

Explain what a change prevents, not what it changes; the diff already says
what. Where a decision could reasonably have gone the other way, say why it
went this way. Keep the subject line under ~72 characters and write in the
imperative.
