"""Командная строка: единственный интерфейс pip/uvx-пакета.

Только локальная конверсия. Работа с внешним сервером -- это канал Docker
(docker exec внутрь контейнера) и настройка в десктопном приложении; сетевого
режима здесь нет сознательно, чтобы у инструмента, который ценен локальностью,
не появилось сетевых отказов.
"""
import argparse
import sys
from pathlib import Path

from trimitdown import __version__
from trimitdown.convert import ConversionError, convert_bytes, convert_path


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
    convert.add_argument(
        "--type",
        dest="suffix",
        help='file extension for stdin input, e.g. ".pdf" -- required with "-"',
    )
    return parser


def _run_convert(args) -> int:
    if args.path == "-":
        if not args.suffix:
            print(
                'reading from stdin needs --type, e.g. --type .pdf: the extension '
                "cannot be recovered from a stream",
                file=sys.stderr,
            )
            return 2
        try:
            result = convert_bytes(sys.stdin.buffer.read(), args.suffix)
        except ConversionError as e:
            print(f"could not convert stdin: {e}", file=sys.stderr)
            return 1
    else:
        path = Path(args.path)
        if not path.is_file():
            print(f"no such file: {path}", file=sys.stderr)
            return 1
        try:
            result = convert_path(path)
        except ConversionError as e:
            print(f"could not convert {path}: {e}", file=sys.stderr)
            return 1

    if args.output:
        Path(args.output).write_text(result.text, encoding="utf-8")
    else:
        # Явная запись в буфер: на Windows консольная кодировка по умолчанию не
        # переваривает вывод конвертации (m³/h, ≥, кириллица) и печать падает.
        sys.stdout.buffer.write(result.text.encode("utf-8"))
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
