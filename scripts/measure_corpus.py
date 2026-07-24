"""Run both PDF converters over your own PDFs and print a comparable summary.

The numbers in docs/pdf-engine.md come from two private collections, 891
documents in all, skewed toward Russian technical material. Nobody else can re-run
them: the corpus is third-party and is not in this repository. This script is
the answer to that -- it re-measures the same defects on *your* documents, so
the claim can be checked against a corpus whose failure modes nobody here has
seen.

    python scripts/measure_corpus.py /path/to/your/pdfs

The summary printed to stdout carries no filenames, no paths and no document
text: it is aggregate counts only, safe to paste into an issue. Per-document
rows go to a separate file (--details), which stays on your machine.

That summary is the most useful thing you can send back, especially if this
engine loses to markitdown on any row of it.
"""

import argparse
import json
import os
import random
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Per-document rows carry corpus filenames, so they are written outside the repo
# tree (a sibling dir), where they cannot be committed. See tests/conftest.py.
PRIVATE_DIR = Path(os.environ.get("TRIMITDOWN_PRIVATE") or REPO_ROOT.parent / "trimitdown-private")

import pdfplumber  # noqa: E402
import tiktoken  # noqa: E402

import trimitdown_pdf  # noqa: E402
from trimitdown_pdf import TABLE_SETTINGS, TEXT_SETTINGS, pdf_to_markdown  # noqa: E402

# 26+ letters with no break. Real words that long are vanishingly rare in either
# language here; runs this long are two or more words fused by a word-gap
# threshold that was too wide for the font size. Same expression as the sweep
# scripts use, so the counts stay comparable with the published ones.
GLUED = re.compile(r"[A-Za-zА-Яа-яЁё]{26,}")

# Parity is scored over digit CHARACTERS, not number tokens. Tokens were tried
# first (two-or-more digits, matched with r"\d+(?:[.,]\d+)*") and had to be
# withdrawn: they measure re-tokenisation, not data loss. This engine reshapes a
# ruled grid into cells, and a cell boundary that lands mid-number turns one
# "10" into a "1" and a "0" -- two tokens the length filter then discarded, so
# the document scored as having *lost* a number it still contains in full. On
# one 349-page catalogue that single effect produced 791 numbers "lost" and zero
# digits lost. Measured over all 891 documents of both private corpora, digit
# deficit was 0 for both engines on every single document, while the token
# metric claimed 1492 losses for this engine and 1356 for markitdown -- all of
# it re-tokenisation, none of it data.
#
# Digit counts are invariant under splitting and joining, so what survives is
# what the row claims to measure: a digit the converter dropped, or one it
# emitted twice.
#
# What it therefore cannot see, and no row here does: order. Two overlapping
# text layers whose glyphs interleave into "123" + ".4XYZ" -> ".14X2Y3Z"
# (an invented example of a real shape -- the corpus documents that do this
# are the owner's own and nothing from them is reproduced here)
# conserve every digit and score clean. That failure is real and is in the
# corpus; it needs a different row, not a wider regex here.
DIGIT = re.compile(r"\d")

# A page with no text layer renders to a marker naming the page number rather
# than to nothing at all (see trimitdown_pdf.pdf_to_markdown). That page number
# is a digit, and the baseline it is scored against -- the page's own text -- is
# empty, that being the whole point. Scored naively the marker therefore reads as
# the engine duplicating data: over both private corpora it produced 837 such
# "duplicated" digits across 124 documents, every one of them a page number
# inside a marker, and 0 remained once marker lines were excluded. The marker is
# the engine reporting an absence, not data it claims to have extracted, so the
# parity rows do not score it.
#
# The token row still counts it, deliberately. The marker occupies real space in
# the output and the reader pays for it; subtracting it there would flatter this
# engine on the one row where the marker genuinely costs something.
NO_TEXT_MARKER = "no extractable text layer"

# A document that encodes almost no word spacing at the source glues heavily in
# any converter, and a handful of them will otherwise carry the whole glue
# result: on the private corpora six such files held 1388 of markitdown's 1495
# glued runs. They are reported separately so that cannot happen. The criterion
# is a property of the document -- how badly the STOCK converter glues it -- and
# never of this engine's own output, so it cannot be tuned to flatter the result.
# The threshold sits in a wide empty gap in the data (the next document down
# scored 15), not at a value chosen to move the headline.
BROKEN_SOURCE_GLUE = 50


def without_engine_markers(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if NO_TEXT_MARKER not in ln)

# Mojibake: cp1251 Cyrillic whose bytes were decoded as latin-1 lands almost
# entirely in U+00C0-U+00FF, so a document rendered through the wrong codec
# comes out as a dense run of accented Latin letters. This is a DIAGNOSTIC row
# only -- nothing in the engine repairs it, and nothing should on the strength
# of this counter alone. It is here so that the next full corpus re-measure
# yields the frequency for free rather than needing its own sweep.
#
# The character count alone cannot separate "a document is mojibake" from "a
# document is French": a page of legitimate accented Latin scores on this row
# too. The per-document share is what distinguishes them, hence the second row
# -- real prose in any Latin-script language stays well under 15% of its own
# characters, while a wholly mis-decoded Cyrillic document is most of them.
MOJIBAKE = re.compile(r"[À-ÿ]")
MOJIBAKE_DOC_SHARE = 0.15

ENC = tiktoken.get_encoding("cl100k_base")

ENGINES = ("markitdown", "trimitdown")


def digits_in(text: str) -> Counter:
    return Counter(DIGIT.findall(text))


def table_rows(text: str) -> int:
    return sum(1 for line in text.splitlines() if line.startswith("|"))


def analyse(path: Path) -> tuple[Counter, int]:
    """Baseline digits and ruled-grid count for one document.

    The baseline is pdfplumber's own page text -- neither converter's output.
    Both engines are then scored against it in both directions: digits it has
    that they lost, and digits they emit more often than it does.

    Read the digit rows as a self-check on THIS engine, not as a head-to-head.
    markitdown pastes a page's text through in reading order, so its digits are
    the baseline's digits: over all 891 documents of the private corpora it
    scored exactly zero in both directions on every single one. A row the other
    engine cannot lose is not a comparison. It is still worth printing, because
    this engine restructures pages and therefore *can* repeat a digit -- and on
    those same documents it once repeated 3138 of them, every one traced to a
    single bug in cell rendering (see _extract_rows), and 0 afterwards.
    """
    grids = 0
    no_text_pages = 0
    base = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            grids += len(page.find_tables(TABLE_SETTINGS))
            # A property of the corpus, not of either engine: both are handed the
            # same unreadable pages. Reported so a reader can see what share of
            # their own documents is scans before reading the rows below.
            no_text_pages += not page.chars
            base.append(page.extract_text(**TEXT_SETTINGS) or "")
            # Without this pdfplumber keeps every page's parsed objects alive
            # for the lifetime of the document. On a large scanned file that is
            # the difference between a few hundred MB and an OOM kill.
            page.flush_cache()
    return digits_in("\n\n".join(base)), grids, no_text_pages


def score(text: str, baseline: Counter, has_grids: bool) -> dict:
    out = digits_in(without_engine_markers(text))
    mojibake = len(MOJIBAKE.findall(text))
    return {
        "glued": len(GLUED.findall(text)),
        "mojibake": mojibake,
        # A whole document decoded through the wrong codec, as opposed to a
        # handful of accented characters in otherwise clean text.
        "mojibake_doc": int(mojibake > MOJIBAKE_DOC_SHARE * len(text)),
        # Rows emitted for a document in which pdfplumber found no ruled grid at
        # all. Every one of them is prose reshaped into a table -- the defect
        # that motivated the row-fill validation stage. Documents that do have
        # grids are excluded rather than judged, because telling a correct row
        # from an invented one there needs labels this script does not have.
        "phantom_rows": 0 if has_grids else table_rows(text),
        "digit_excess": sum((out - baseline).values()),
        "digit_deficit": sum((baseline - out).values()),
        "tokens": len(ENC.encode(text)),
    }


def convert(engine: str, path: Path, markitdown) -> str:
    if engine == "trimitdown":
        return pdf_to_markdown(path)
    return markitdown.convert(str(path)).text_content


def pct(part: int, whole: int) -> str:
    return f"{part} ({part / whole * 100:.0f}%)" if whole else str(part)


def report(rows: list[dict], totals: dict, failures: dict, elapsed: dict,
           n_docs: int, n_bytes: int, n_gridless: int, n_notext: int) -> str:
    def line(label: str, key: str, fmt=str) -> str:
        a, b = fmt(totals["markitdown"][key]), fmt(totals["trimitdown"][key])
        return f"| {label} | {a} | {b} |"

    files_with_glue = {
        e: sum(1 for r in rows if r[e]["glued"]) for e in ENGINES
    }
    files_mojibake = {
        e: sum(1 for r in rows if r[e]["mojibake_doc"]) for e in ENGINES
    }
    # Every row here converted on both engines, so "s" is always present.
    med_s = {
        e: statistics.median([r[e]["s"] for r in rows] or [0]) for e in ENGINES
    }
    versions = {
        "python": ".".join(str(v) for v in sys.version_info[:3]),
        "pdfplumber": pdfplumber.__version__,
        "trimitdown_pdf": trimitdown_pdf.__version__,
    }

    out = [
        "### measure_corpus.py",
        "",
        f"- documents: {n_docs} ({n_bytes / 1024 / 1024:.1f} MB), "
        f"{n_gridless} of them with no ruled grid anywhere",
        f"- pages with no text layer: {n_notext} "
        f"(scans -- nothing for either engine to extract, and neither does OCR)",
        "- versions: " + ", ".join(f"{k} {v}" for k, v in versions.items()),
        "",
        "| | markitdown | TrimItDown |",
        "|---|---|---|",
        line("glued word runs", "glued"),
        f"| documents containing glue | {pct(files_with_glue['markitdown'], n_docs)} "
        f"| {pct(files_with_glue['trimitdown'], n_docs)} |",
        line("mojibake characters (U+00C0-U+00FF)", "mojibake"),
        f"| documents over {MOJIBAKE_DOC_SHARE:.0%} mojibake "
        f"| {pct(files_mojibake['markitdown'], n_docs)} "
        f"| {pct(files_mojibake['trimitdown'], n_docs)} |",
        line("table rows on grid-less documents", "phantom_rows"),
        line("digits duplicated vs page text", "digit_excess"),
        line("digits lost vs page text", "digit_deficit"),
        f"| conversion failures | {failures['markitdown']} | {failures['trimitdown']} |",
        line("output tokens", "tokens"),
        # Both, because they answer different questions and on this corpus they
        # disagree. The median is the one a reader converting a document should
        # read; the total is the one someone converting a whole archive should.
        f"| median seconds per document | {med_s['markitdown']:.3f} s "
        f"| {med_s['trimitdown']:.3f} s |",
        f"| total runtime | {elapsed['markitdown']:.1f} s | {elapsed['trimitdown']:.1f} s |",
        "",
    ]

    # A total says which engine wins overall; it says nothing about whether one
    # document is carrying the whole result. The median does, and a corpus where
    # the two disagree is exactly the interesting report.
    for key, label in (("glued", "glued runs"), ("digit_deficit", "digits lost")):
        meds = {e: statistics.median([r[e][key] for r in rows] or [0]) for e in ENGINES}
        out.append(f"median {label} per document: markitdown {meds['markitdown']:.0f}, "
                   f"TrimItDown {meds['trimitdown']:.0f}")

    out += [
        "",
        "Numbers above are counts over the whole corpus. No filenames, paths or",
        "document text are included -- this block is safe to paste as-is.",
    ]
    return "\n".join(out)


def split_by_source_quality(rows: list) -> tuple[list, list]:
    """Separate the well-formed documents from the broken-source ones.

    The verdict is read off the STOCK converter's glue count, never off this
    engine's, so no change here can move a document out of the headline to make
    this engine look better.
    """
    well = [r for r in rows if r["markitdown"]["glued"] <= BROKEN_SOURCE_GLUE]
    broken = [r for r in rows if r["markitdown"]["glued"] > BROKEN_SOURCE_GLUE]
    return well, broken


def aggregate(rows: list) -> tuple:
    """Corpus figures for a set of rows.

    Derived from the rows rather than accumulated while measuring, so that every
    number in one summary shares a single denominator. Accumulating during the
    sweep counted documents that parsed but failed to convert, which left the
    document count and the gridless count describing different populations.
    """
    totals = {e: Counter() for e in ENGINES}
    elapsed = {e: 0.0 for e in ENGINES}
    n_bytes = n_gridless = n_notext = 0
    for r in rows:
        n_bytes += r["bytes"]
        n_gridless += not r["grids"]
        n_notext += r["notext"]
        for e in ENGINES:
            # "s" is timing, not a count; it must not enter the count columns.
            totals[e].update({k: v for k, v in r[e].items() if k != "s"})
            elapsed[e] += r[e]["s"]
    return totals, elapsed, n_bytes, n_gridless, n_notext


def main() -> int:
    # Converted documents carry characters the console codepage cannot encode
    # (m³/h, ≥, Cyrillic); on a Russian Windows the first one aborts the run.
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("corpus", type=Path, nargs="+",
                    help="one or more directories of PDFs, searched recursively. Pass every "
                         "collection to ONE run: measuring them separately and adding the "
                         "summaries up double-counts whatever appears in both, and loses the "
                         "medians entirely")
    ap.add_argument("--details", type=Path, default=PRIVATE_DIR / "measure-corpus-details.jsonl",
                    help="per-document rows, including filenames; written outside the repo "
                         "tree (the trimitdown-private sibling) so it cannot be committed")
    ap.add_argument("--max-mb", type=float, default=10.0,
                    help="skip documents larger than this (0 disables); the published "
                         "numbers used 10")
    ap.add_argument("--limit", type=int, default=0,
                    help="measure only this many documents, drawn at random (see --seed); "
                         "a few dozen is enough to see whether the two engines differ on "
                         "your material. Default: all of them")
    ap.add_argument("--seed", type=int, default=0,
                    help="random seed for --limit's sample; the same seed picks the same "
                         "documents, so a --limit run is reproducible")
    args = ap.parse_args()

    for root in args.corpus:
        if not root.is_dir():
            print(f"not a directory: {root}", file=sys.stderr)
            return 1

    limit = args.max_mb * 1024 * 1024
    # Same basename in two collections is the same document. Counting it twice
    # inflates every total and silently weights it double in the medians.
    by_name = {}
    for root in args.corpus:
        for q in root.rglob("*.pdf"):
            if not limit or q.stat().st_size < limit:
                by_name.setdefault(q.name, q)
    paths = sorted(by_name.values())
    if args.limit and args.limit < len(paths):
        # A random sample, not the alphabetical head: filenames cluster by
        # source, so the first N documents are one folder's worth, not a
        # cross-section. Seeded, so the run stays reproducible. Sorted back into
        # path order only so progress output and the details file read sensibly.
        paths = sorted(random.Random(args.seed).sample(paths, args.limit))
    if not paths:
        print(f"no PDFs under {', '.join(str(r) for r in args.corpus)}", file=sys.stderr)
        return 1

    from markitdown import MarkItDown
    markitdown = MarkItDown()

    rows = []
    failures = {e: 0 for e in ENGINES}

    print(f"{len(paths)} documents", file=sys.stderr, flush=True)
    args.details.parent.mkdir(parents=True, exist_ok=True)
    with args.details.open("w", encoding="utf-8") as fh:
        for i, path in enumerate(paths, 1):
            try:
                baseline, grids, no_text_pages = analyse(path)
            except Exception as e:
                # A document neither engine can parse measures nothing about
                # either of them, so it leaves no row rather than a zeroed one.
                fh.write(json.dumps({"file": path.name, "unreadable": str(e)[:200],
                                     }, ensure_ascii=False) + "\n")
                continue

            row = {"file": path.name, "grids": grids,
                   "bytes": path.stat().st_size, "notext": no_text_pages}
            for engine in ENGINES:
                started = time.perf_counter()
                try:
                    text = convert(engine, path, markitdown)
                except Exception as e:
                    failures[engine] += 1
                    row[engine] = {"error": f"{type(e).__name__}: {e}"[:200]}
                    continue
                finally:
                    took = time.perf_counter() - started
                row[engine] = score(text, baseline, bool(grids))
                # Conversion seconds for this one document. Kept per document
                # rather than accumulated: a corpus total answers "how long to
                # convert this corpus", not "how long will my document take",
                # because a few very long documents carry most of the total --
                # and aggregate() needs the per-document value to total a
                # subset of the corpus without re-measuring it.
                row[engine]["s"] = round(took, 4)

            # Only documents both engines converted enter the comparison; a row
            # where one side failed would otherwise credit that side with zero
            # defects for a document it never produced.
            if all("error" not in row[e] for e in ENGINES):
                rows.append(row)
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            if i % 25 == 0:
                print(f"{i}/{len(paths)}", file=sys.stderr, flush=True)
                fh.flush()

    if not rows:
        print("no document converted through both engines", file=sys.stderr)
        return 1

    # The headline is the well-formed documents; the broken-source ones follow
    # in their own block. This split used to live only in the prose of
    # docs/pdf-engine.md, and a rerun that read the summary alone folded them
    # back into the headline -- which moved the glue result from 2.0x to 3.2x in
    # this engine's own favour. It is code now so a rerun cannot lose it.
    well, broken = split_by_source_quality(rows)
    if not well:
        print("every document scored as broken at the source", file=sys.stderr)
        return 1

    totals, elapsed, n_bytes, n_gridless, n_notext = aggregate(well)
    print(report(well, totals, failures, elapsed, len(well), n_bytes, n_gridless,
                 n_notext))
    if broken:
        b_totals, _, _, _, _ = aggregate(broken)
        print()
        print(f"Reported separately: {len(broken)} document(s) that encode almost no word")
        print(f"spacing at the source (markitdown glues over {BROKEN_SOURCE_GLUE} runs in each).")
        print(f"Glued runs there: markitdown {b_totals['markitdown']['glued']}, "
              f"TrimItDown {b_totals['trimitdown']['glued']}. They are excluded from the")
        print("table above so that a few pathological files cannot carry the result.")
    print(f"\nper-document rows (with filenames): {args.details}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
