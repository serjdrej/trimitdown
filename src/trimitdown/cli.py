"""Командная строка: единственный интерфейс pip/uvx-пакета.

Только локальная конверсия. Работа с внешним сервером -- это канал Docker
(docker exec внутрь контейнера) и настройка в десктопном приложении; сетевого
режима здесь нет сознательно, чтобы у инструмента, который ценен локальностью,
не появилось сетевых отказов.

Three commands: `convert` (optionally writing a review directory for the PDF
pages it cannot vouch for), `assemble` (putting reviewed pages back) and
`render` (page images on demand, for checking digits on text-layer pages).
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from trimitdown import __version__
from trimitdown.convert import ConversionError, convert_bytes, convert_path
from trimitdown.office_inspect import summary_phrase
from trimitdown.pdf_route import render_markdown, summary_line


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trimitdown",
        description="Convert documents to LLM-ready markdown.",
    )
    parser.add_argument("--version", action="version", version=f"trimitdown {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)
    convert = sub.add_parser("convert", help="convert one document to markdown")
    convert.add_argument("path", help='file to convert, or "-" to read stdin')
    convert.add_argument("-o", "--output", help="write markdown here instead of stdout")
    convert.add_argument("--page-anchors", action="store_true",
                         help="PDF only: start each page with <!-- page N -->, for citing by page")
    convert.add_argument(
        "--type",
        dest="suffix",
        help='file extension for stdin input, e.g. ".pdf" -- required with "-"',
    )
    convert.add_argument(
        "--accept-changes",
        action="store_true",
        help="DOCX only: convert a document with unresolved tracked changes anyway and "
             "print the text with every change accepted (the default is to refuse). "
             "DOC and RTF with tracked changes are refused either way",
    )
    convert.add_argument(
        "--report", metavar="PATH",
        help="write a JSON report (format, tracked changes, what the Markdown leaves out; "
             "for a PDF, page counts per route) to PATH when the conversion succeeds",
    )
    review = convert.add_argument_group(
        "review (PDF only)",
        "Write the pages that need checking -- scans, unverified OCR layers, "
        "unreadable text layers -- into a directory an agent reconciles. "
        "Nothing is reviewed by this program; see REVIEW.md in that directory.",
    )
    review.add_argument("--review-dir", metavar="DIR",
                        help="write document.md, manifest.json, REVIEW.md and page images here")
    review.add_argument("--review-markers", choices=["ru", "en"], default="ru",
                        help="marks the review rule asks for: ru ([неразборчиво], "
                             "=== стр. N ===) or en ([illegible], === page N ===); default ru")
    review.add_argument("--review-substitute", action="store_true",
                        help="also send pages whose text was taken from the text layer")
    review.add_argument("--no-ocr", action="store_true",
                        help="do not run Tesseract; pages without a candidate are still sent")
    review.add_argument("--ocr-fresh", action="store_true",
                        help="run Tesseract even on scans that carry an OCR layer")
    review.add_argument("--ocr-lang", default="rus",
                        help="Tesseract languages, e.g. rus or rus+eng; default rus")
    review.add_argument("--tesseract", metavar="PATH",
                        help="the tesseract executable (default: TRIMITDOWN_TESSERACT, PATH, "
                             "then the usual install locations)")
    review.add_argument("--tessdata-dir", metavar="DIR",
                        help="where the .traineddata files are, if not Tesseract's own")

    assemble = sub.add_parser("assemble", help="put reviewed pages back into the document")
    assemble.add_argument("review_dir", help="a directory written by convert --review-dir")
    assemble.add_argument("-o", "--output", help="write markdown here instead of stdout")
    assemble.add_argument("--no-page-anchors", action="store_true",
                          help="drop the <!-- page N --> line that starts each page")
    assemble.add_argument("--allow-missing", action="store_true",
                          help="keep the unverified text of pages nobody reviewed yet")

    render = sub.add_parser("render", help="write page images of a PDF")
    render.add_argument("path", help="the PDF")
    render.add_argument("--pages", required=True, help="pages from 1, e.g. 5,7,10-12")
    render.add_argument("-o", "--output", required=True, metavar="DIR",
                        help="directory to write the images into")
    return parser


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        # Явная запись в буфер: на Windows консольная кодировка по умолчанию не
        # переваривает вывод конвертации (m³/h, ≥, кириллица) и печать падает.
        sys.stdout.buffer.write(text.encode("utf-8"))


def _review(args, source: Path, result) -> int:
    from trimitdown.review import ReviewError, prepare_review

    if result.pages is None:
        print("--review-dir works on PDFs only", file=sys.stderr)
        return 2
    try:
        manifest = prepare_review(
            source,
            args.review_dir,
            ocr=not args.no_ocr,
            ocr_lang=args.ocr_lang,
            ocr_fresh=args.ocr_fresh,
            tesseract=args.tesseract,
            tessdata_dir=args.tessdata_dir,
            include_substitute=args.review_substitute,
            markers=args.review_markers,
            routes=list(result.pages),
        )
    except (ReviewError, OSError) as e:
        print(f"could not write the review directory: {e}", file=sys.stderr)
        return 1

    summary = manifest["summary"]
    print(summary_line(list(result.pages), len(summary["review_pages"])), file=sys.stderr)
    without = summary["without_candidate"]
    if without:
        why = {
            "unavailable": "Tesseract was not found",
            "lang_missing": f"Tesseract has no {', '.join(manifest['ocr'].get('missing', []))}",
            "disabled": "--no-ocr",
        }.get(manifest["ocr"]["status"], "OCR produced no text")
        noun = "page goes" if len(without) == 1 else "pages go"
        print(f"{len(without)} {noun} to review without a candidate ({why}): "
              "the reviewer transcribes them from the image", file=sys.stderr)
    print(f"review directory: {args.review_dir}", file=sys.stderr)
    if args.output:
        _write(_document_text(args, result), args.output)
    return 0


def _run_convert(args) -> int:
    temp_path = None
    if args.path == "-":
        if not args.suffix:
            print(
                'reading from stdin needs --type, e.g. --type .pdf: the extension '
                "cannot be recovered from a stream",
                file=sys.stderr,
            )
            return 2
        # Routing happens on the extension, and the PDF route is selected by
        # ".pdf" exactly. A bare "pdf" names a temp file with no extension at
        # all, so the document silently falls through to the stock converter --
        # measured on the ruled-table fixture, the whole table came back as
        # loose lines. Silent worse output is the one failure this project
        # exists to prevent, so accept both spellings rather than reject one.
        suffix = args.suffix if args.suffix.startswith(".") else f".{args.suffix}"
        data = sys.stdin.buffer.read()
        try:
            if args.review_dir:
                # The review directory needs the PDF on disk for its page images.
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(data)
                    temp_path = Path(tmp.name)
                result = convert_path(temp_path, accept_changes=args.accept_changes)
            else:
                result = convert_bytes(data, suffix, accept_changes=args.accept_changes)
        except ConversionError as e:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
            print(f"could not convert stdin: {e}", file=sys.stderr)
            return 1
        source = temp_path
    else:
        path = Path(args.path)
        if not path.is_file():
            print(f"no such file: {path}", file=sys.stderr)
            return 1
        try:
            result = convert_path(path, accept_changes=args.accept_changes)
        except ConversionError as e:
            print(f"could not convert {path}: {e}", file=sys.stderr)
            return 1
        source = path

    try:
        if args.report:
            try:
                _write_report(result, args.report)
            except OSError as e:
                print(f"could not write the report: {e}", file=sys.stderr)
                return 1
        if args.review_dir:
            return _review(args, source, result)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    if result.pages and any(page.path != "accept" for page in result.pages):
        # Silent on a clean document; one line when some page did not come from
        # pdf-inspector, so the change in the output is never invisible.
        print(summary_line(list(result.pages)), file=sys.stderr)
    _print_office_summary(result)
    _write(_document_text(args, result), args.output)
    return 0


def _print_office_summary(result) -> None:
    # The same words as the <!-- trimitdown: ... --> line at the top of the
    # Markdown, built from the same report. Silent when there is nothing to say.
    phrase = summary_phrase(result.report or {})
    if phrase:
        print(f"trimitdown: {phrase}", file=sys.stderr)


def _write_report(result, path: str) -> None:
    report = result.report if result.report is not None else {"schema": 1}
    Path(path).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _document_text(args, result) -> str:
    # --page-anchors only means something for a PDF, the one format with pages.
    if getattr(args, "page_anchors", False) and result.pages:
        return render_markdown(list(result.pages), page_anchors=True)
    return result.text


def _run_assemble(args) -> int:
    from trimitdown.review import ReviewError, assemble

    try:
        text = assemble(args.review_dir, allow_missing=args.allow_missing,
                        page_anchors=not args.no_page_anchors)
    except ReviewError as e:
        print(f"could not assemble {args.review_dir}: {e}", file=sys.stderr)
        return 1
    _write(text, args.output)
    return 0


def _run_render(args) -> int:
    from trimitdown.review import render_pages

    path = Path(args.path)
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 1
    try:
        written = render_pages(path, args.pages, args.output)
    except ValueError as e:
        print(f"could not render {path}: {e}", file=sys.stderr)
        return 2
    except Exception as e:  # pdfium refusing the file
        print(f"could not render {path}: {e}", file=sys.stderr)
        return 1
    for file in written:
        print(os.fspath(file), file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    # Converted documents and the paths they came from carry characters the console
    # codepage cannot encode (m³/h, ≥, Cyrillic); on a Russian Windows the first one
    # would abort the process. stdout is written as bytes below for the document
    # body, but error messages go through the text layer and need this.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    args = _build_parser().parse_args(argv)
    if args.command == "convert":
        return _run_convert(args)
    if args.command == "assemble":
        return _run_assemble(args)
    if args.command == "render":
        return _run_render(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
