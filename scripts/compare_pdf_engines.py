"""Convert a PDF with both markitdown's stock converter and TrimItDown's engine.

Reproduces the before/after comparison shown in the README:

    python scripts/compare_pdf_engines.py tests/data/sample-service-report.pdf

With no argument it uses the bundled sample. Both converters read the same file,
so any difference in the output is a difference between the engines.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.pdf_extract import pdf_to_markdown  # noqa: E402

DEFAULT_SAMPLE = Path(__file__).resolve().parent.parent / "tests" / "data" / "sample-service-report.pdf"


def main() -> int:
    # Converted documents carry characters the console's default codepage cannot encode
    # (m³/h, ≥, Cyrillic). When stdout is redirected or piped, Python falls back to that
    # codepage -- cp1251 on a Russian Windows -- and the first such character aborts the
    # run. A filename passed as an argument can do the same to stderr.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SAMPLE
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1

    from markitdown import MarkItDown

    print("=" * 70)
    print("STOCK markitdown")
    print("=" * 70)
    print(MarkItDown().convert(str(path)).text_content)

    print("=" * 70)
    print("TrimItDown engine")
    print("=" * 70)
    print(pdf_to_markdown(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
