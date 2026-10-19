"""The review hand-off: a directory an agent reconciles, and the way back.

`prepare_review` routes a PDF exactly as `convert` does and then writes what a
reviewing agent needs for the pages the route could not vouch for: their images,
a candidate text (an OCR layer already in the PDF, or fresh Tesseract output),
a manifest, and the procedure (REVIEW.md). `assemble` puts the reviewed pages
back. The code reviews nothing itself.

Kept apart from trimitdown.convert on purpose: convert is "a path in, text
out", and this module writes files and starts processes. convert.py does not
import it.

Every way this can quietly do less than asked -- no Tesseract, no language
data, no orientation data, OCR failing on a page -- is written into the
manifest and reported on stderr by the CLI. A page without a candidate still
goes to review; it is never dropped.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata, resources
from pathlib import Path

from trimitdown import __version__
from trimitdown.pdf_route import (
    REVIEW_COST_PER_PAGE_USD,
    PageRoute,
    open_reference,
    path_counts,
    route_pdf,
)
from trimitdown.text_metrics import text_metrics

MANIFEST_SCHEMA = 1
RENDER_DPI = 300
OCR_TIMEOUT_S = 120
# Below this the owner's rule says: do not rotate, look at the page.
ORIENTATION_MIN_CONFIDENCE = 10.0
# A single image counts as "the whole page" when its bounds match the page box
# to within this fraction of the page's width and height.
FULL_PAGE_TOLERANCE = 0.02

# Review marks. "ru" is what the owner's rule and its quote checker use; "en"
# is the same set in English for skills that do not read Russian.
MARKERS = {
    "ru": {
        "PAGE_HEADER": "=== стр. N ===",
        "ILLEGIBLE": "[неразборчиво]",
        "UNSURE": "слово[?]",
        "CODE_UNSURE": "код[?]",
        "HANDWRITTEN": "[рукописно: …]",
        "SIGNATURE": "[подпись]",
        "SEAL": "[печать]",
        "STAMP": "[штамп]",
        "RECEIPT": (
            "Страницы просмотрены: <диапазон/перечень>\n"
            "Метод по страницам: <страницы — текстовый слой / OCR + сверка с изображением; пустые отдельно>\n"
            "Сверка цифр глазами: <страницы и адреса: статья, часть, пункт, номер, дата, суммы>\n"
            "Страницы НЕ просмотрены: <диапазон/перечень или нет>"
        ),
    },
    "en": {
        "PAGE_HEADER": "=== page N ===",
        "ILLEGIBLE": "[illegible]",
        "UNSURE": "word[?]",
        "CODE_UNSURE": "code[?]",
        "HANDWRITTEN": "[handwritten: …]",
        "SIGNATURE": "[signature]",
        "SEAL": "[seal]",
        "STAMP": "[stamp]",
        "RECEIPT": (
            "Pages viewed: <range/list>\n"
            "Method per page: <pages — text layer / OCR + checked against the image; empty pages separately>\n"
            "Digits checked by eye: <pages and places: article, part, item, number, date, sums>\n"
            "Pages NOT viewed: <range/list or none>"
        ),
    },
}

# Both header spellings are accepted whatever the markers setting: a reviewer
# following the Russian rule on an English directory still has to get back in.
_PAGE_HEADER = re.compile(r"^===\s*(?:стр\.|page)\s*(\d+)\s*===\s*$", re.MULTILINE | re.IGNORECASE)
_ANCHOR = re.compile(r"^<!-- page (\d+) -->\n", re.MULTILINE)
_PAGE_FILE = re.compile(r"^p(\d{4,})\.txt$")


class ReviewError(Exception):
    """A review directory that cannot be written or assembled. The message says why."""


# --- Tesseract -----------------------------------------------------------------

def _known_locations() -> list[Path]:
    places = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(variable)
        if base:
            places.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
    places += [Path("/opt/homebrew/bin/tesseract"), Path("/usr/local/bin/tesseract"),
               Path("/usr/bin/tesseract")]
    return places


def find_tesseract(explicit: str | list[str] | None = None) -> list[str] | None:
    """The command that runs Tesseract, or None.

    Order: an explicit path (or a ready command list), TRIMITDOWN_TESSERACT,
    PATH, then the places installers put it without touching PATH. "command not
    found" does not mean Tesseract is absent: the Windows installer can leave
    PATH alone, which is why the fixed locations are checked at all.
    """
    if isinstance(explicit, (list, tuple)):
        return list(explicit)
    for candidate in (explicit, os.environ.get("TRIMITDOWN_TESSERACT")):
        if candidate:
            return [candidate] if Path(candidate).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return [found]
    for place in _known_locations():
        if place.is_file():
            return [str(place)]
    return None


@dataclass
class Tesseract:
    cmd: list[str]
    tessdata_dir: str | None = None

    def _run(self, args: list[str], timeout: float = OCR_TIMEOUT_S) -> subprocess.CompletedProcess:
        extra = ["--tessdata-dir", self.tessdata_dir] if self.tessdata_dir else []
        env = dict(os.environ, OMP_THREAD_LIMIT="1")
        # Bytes, decoded as UTF-8 here: on Windows the console code page would
        # mangle Cyrillic if the process output were decoded as text.
        return subprocess.run(self.cmd + args + extra, capture_output=True,
                              timeout=timeout, env=env)

    def version(self) -> str | None:
        try:
            out = self._run(["--version"], timeout=30)
        except (OSError, subprocess.SubprocessError):
            return None
        text = (out.stdout + out.stderr).decode("utf-8", "replace")
        match = re.search(r"tesseract\s+v?(\d+(?:\.\d+)+)", text, re.IGNORECASE)
        return match.group(1) if match else None

    def langs(self) -> set[str]:
        try:
            out = self._run(["--list-langs"], timeout=30)
        except (OSError, subprocess.SubprocessError):
            return set()
        lines = (out.stdout + out.stderr).decode("utf-8", "replace").splitlines()
        return {line.strip() for line in lines
                if line.strip() and not line.lower().startswith("list of")}

    def orientation(self, image: Path) -> tuple[int | None, float | None]:
        """(degrees to rotate clockwise, confidence) from OSD, or (None, None)."""
        try:
            out = self._run([str(image), "stdout", "--psm", "0", "-l", "osd"])
        except (OSError, subprocess.SubprocessError):
            return None, None
        text = (out.stdout + out.stderr).decode("utf-8", "replace")
        rotate = re.search(r"Rotate:\s*(\d+)", text)
        confidence = re.search(r"Orientation confidence:\s*([\d.]+)", text)
        if not rotate:
            return None, None
        return int(rotate.group(1)), float(confidence.group(1)) if confidence else None

    def ocr(self, image: Path, lang: str) -> str:
        out = self._run([str(image), "stdout", "-l", lang, "--psm", "3"])
        if out.returncode != 0:
            raise RuntimeError(out.stderr.decode("utf-8", "replace").strip()[:300])
        return out.stdout.decode("utf-8", "replace")


# --- page images ----------------------------------------------------------------

def _image_objects(pdfium_page) -> list:
    import pypdfium2.raw as pdfium_c

    return list(pdfium_page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))


def image_coverage(pdfium_page) -> float:
    """Share of the page under images, as a union on a 50x50 grid.

    Approximate on purpose: it is a manifest metric, not a routing input.
    Images nested in form XObjects may report form-space bounds.
    """
    images = _image_objects(pdfium_page)
    if not images:
        return 0.0
    left, bottom, right, top = pdfium_page.get_bbox()
    width, height = max(right - left, 1e-6), max(top - bottom, 1e-6)
    n = 50
    covered = set()
    for image in images:
        x0, y0, x1, y1 = image.get_bounds()
        c0 = max(0, int((x0 - left) / width * n))
        c1 = min(n, math.ceil((x1 - left) / width * n))
        r0 = max(0, int((y0 - bottom) / height * n))
        r1 = min(n, math.ceil((y1 - bottom) / height * n))
        covered.update((c, r) for c in range(c0, c1) for r in range(r0, r1))
    return round(len(covered) / (n * n), 4)


def _single_image_without_mask(reader, page_index: int) -> bool:
    """pypdf's view of the page: exactly one image XObject, no /SMask or /Mask."""
    if reader is None:
        return False
    try:
        page = reader.pages[page_index]
        xobjects = page["/Resources"].get("/XObject")
        if xobjects is None:
            return False
        images = [x.get_object() for x in xobjects.get_object().values()]
        images = [x for x in images if x.get("/Subtype") == "/Image"]
        return len(images) == 1 and "/SMask" not in images[0] and "/Mask" not in images[0]
    except Exception:
        return False


def page_image(pdfium_doc, reader, page_index: int, dest_stem: Path) -> tuple[Path, str]:
    """Write the image of one page. Returns (file, "source" | "render300").

    The owner's rule: the source image when it is the only thing on the page
    and fills it, otherwise a 300 dpi render. "Fills it" is checked strictly --
    one image object, bounds matching the page to 2 %, no mask, no /Rotate, an
    unrotated placement -- because an agent reconciling text against the wrong
    picture produces confident wrong text. Anything doubtful is rendered.

    A source JPEG is copied as JPEG. Everything else becomes PNG: JPEG 2000
    cannot be read by the agent, and CCITT/JBIG2 scans need decoding anyway.
    """
    page = pdfium_doc[page_index]
    try:
        images = _image_objects(page)
        use_source = False
        if len(images) == 1 and page.get_rotation() == 0:
            left, bottom, right, top = page.get_bbox()
            width, height = right - left, top - bottom
            x0, y0, x1, y1 = images[0].get_bounds()
            fits = (abs(x0 - left) <= FULL_PAGE_TOLERANCE * width
                    and abs(x1 - right) <= FULL_PAGE_TOLERANCE * width
                    and abs(y0 - bottom) <= FULL_PAGE_TOLERANCE * height
                    and abs(y1 - top) <= FULL_PAGE_TOLERANCE * height)
            matrix = images[0].get_matrix()
            upright = abs(matrix.b) < 1e-6 and abs(matrix.c) < 1e-6 and matrix.a > 0 and matrix.d > 0
            use_source = fits and upright and _single_image_without_mask(reader, page_index)
        if use_source:
            image = images[0]
            try:
                filters = image.get_filters()
                if filters == ["DCTDecode"]:
                    target = dest_stem.with_suffix(".jpg")
                    image.extract(str(dest_stem))
                    if target.is_file():
                        return target, "source"
                bitmap = image.get_bitmap(render=False)
                target = dest_stem.with_suffix(".png")
                bitmap.to_pil().save(target)
                return target, "source"
            except Exception:
                pass  # fall through to a render
        bitmap = page.render(scale=RENDER_DPI / 72)
        target = dest_stem.with_suffix(".png")
        bitmap.to_pil().save(target)
        return target, "render300"
    finally:
        page.close()


def _rotate_file(image_file: Path, degrees_clockwise: int) -> None:
    from PIL import Image

    with Image.open(image_file) as image:
        rotated = image.rotate(-degrees_clockwise, expand=True)
    rotated.save(image_file)


# --- the directory ----------------------------------------------------------------

def review_rule(markers: str = "ru") -> str:
    """REVIEW.md as written into a review directory: the packaged rule with the
    chosen set of marks filled in."""
    if markers not in MARKERS:
        raise ValueError(f"unknown review markers {markers!r}; expected one of {sorted(MARKERS)}")
    text = (resources.files("trimitdown") / "review_rule.md").read_text(encoding="utf-8")
    for key, value in MARKERS[markers].items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _stem(page: int) -> str:
    return f"p{page:04d}"


def _anchor(page: int) -> str:
    return f"<!-- page {page} -->\n"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _version_of(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


def prepare_review(
    pdf: str | Path,
    out_dir: str | Path,
    *,
    ocr: bool = True,
    ocr_lang: str = "rus",
    ocr_fresh: bool = False,
    tesseract: str | list[str] | None = None,
    tessdata_dir: str | None = None,
    include_substitute: bool = False,
    markers: str = "ru",
    routes: list[PageRoute] | None = None,
) -> dict:
    """Write a review directory for one PDF and return its manifest.

    Refuses a directory that already has files in it: a half-reviewed directory
    overwritten by a second run loses the reviewer's work without a trace.
    """
    import pypdfium2

    if markers not in MARKERS:
        raise ValueError(f"unknown review markers {markers!r}; expected one of {sorted(MARKERS)}")
    pdf = Path(pdf)
    out = Path(out_dir)
    if out.exists() and any(out.iterdir()):
        raise ReviewError(f"{out} is not empty; give a new or empty directory")
    if routes is None:
        routes = route_pdf(pdf)

    def sent(route: PageRoute) -> bool:
        return route.needs_review or (include_substitute and route.path == "substitute")

    def wants_ocr(route: PageRoute) -> bool:
        if route.path == "corrupt":
            return True
        if route.path == "scan":
            return ocr_fresh or route.source != "ocr_layer"
        return False

    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "candidates").mkdir(exist_ok=True)
    (out / "reviewed").mkdir(exist_ok=True)

    # Tesseract is looked for only if some page will want it, and every way it
    # can be missing is recorded rather than worked around: recognising Cyrillic
    # with "eng" because "rus" is absent produces confident garbage.
    ocr_info: dict = {"status": "not_needed"}
    engine = None
    if any(sent(r) and wants_ocr(r) for r in routes):
        if not ocr:
            ocr_info = {"status": "disabled"}
        else:
            cmd = find_tesseract(tesseract)
            if cmd is None:
                ocr_info = {"status": "unavailable"}
            else:
                engine = Tesseract(cmd, tessdata_dir)
                langs = engine.langs()
                ocr_info = {
                    "status": "ok",
                    "path": cmd[-1] if len(cmd) == 1 else " ".join(cmd),
                    "version": engine.version(),
                    "lang": ocr_lang,
                    "osd": "osd" in langs,
                }
                missing = [part for part in ocr_lang.split("+") if part not in langs]
                if missing:
                    ocr_info["status"] = "lang_missing"
                    ocr_info["missing"] = missing
                    engine = None

    pages_out = []
    bodies = []
    reader = open_reference(str(pdf))
    pdfium_doc = pypdfium2.PdfDocument(str(pdf))
    try:
        for route in routes:
            index = route.page - 1
            pdfium_page = pdfium_doc[index]
            try:
                coverage = image_coverage(pdfium_page)
            finally:
                pdfium_page.close()
            entry: dict = {
                "page": route.page,
                "path": route.path,
                "reason": list(route.reasons),
                "source": route.source,
                "review": sent(route),
                "flags": list(route.flags),
            }
            metrics = text_metrics(route.layer_text)
            metrics.update({
                "pi_letters": route.metrics.get("pi_letters", 0),
                "ref_letters": route.metrics.get("ref_letters", 0),
                "layer_chars": route.metrics.get("layer_chars", 0),
                "gate_fired": "gate_fired" in route.flags,
                "image_coverage": coverage,
            })
            entry["metrics"] = metrics

            if entry["review"]:
                stem = _stem(route.page)
                image_file, kind = page_image(pdfium_doc, reader, index, out / "pages" / stem)
                entry["image"] = image_file.relative_to(out).as_posix()
                entry["image_kind"] = kind
                entry["rotation_applied"] = 0
                candidate = ""
                page_ocr: dict
                if route.path == "substitute":
                    candidate, entry["candidate_source"] = route.text, route.source
                    page_ocr = {"status": "not_needed"}
                elif not wants_ocr(route):
                    candidate, entry["candidate_source"] = route.layer_text, "ocr_layer"
                    page_ocr = {"status": "not_needed"}
                elif engine is None:
                    entry["candidate_source"] = "none"
                    page_ocr = {"status": ocr_info["status"]}
                else:
                    page_ocr = _ocr_one(engine, image_file, ocr_lang, ocr_info["osd"], entry)
                    candidate = page_ocr.pop("text", "")
                    entry["candidate_source"] = "tesseract" if candidate.strip() else "none"
                if ocr_fresh and route.source == "ocr_layer":
                    layer_file = out / "candidates" / f"{stem}.layer.txt"
                    layer_file.write_text(route.layer_text, encoding="utf-8")
                    entry["layer_text"] = layer_file.relative_to(out).as_posix()
                candidate_file = out / "candidates" / f"{stem}.txt"
                candidate_file.write_text(candidate, encoding="utf-8")
                entry["candidate_text"] = candidate_file.relative_to(out).as_posix()
                entry["ocr"] = page_ocr
                entry["candidate_metrics"] = text_metrics(candidate)
            pages_out.append(entry)
            bodies.append(_anchor(route.page) + route.text)
    finally:
        pdfium_doc.close()

    review_pages = [p["page"] for p in pages_out if p["review"]]
    without_candidate = [p["page"] for p in pages_out
                         if p["review"] and p.get("candidate_source") == "none"]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "tool": {
            "trimitdown": __version__,
            "pdf_inspector": _version_of("pdf-inspector"),
            "pypdf": _version_of("pypdf"),
            "pypdfium2": _version_of("pypdfium2"),
        },
        "pdf": {"name": pdf.name, "sha256": _sha256(pdf), "page_count": len(routes)},
        "markers": markers,
        "ocr": ocr_info,
        "summary": {
            "paths": path_counts(routes),
            "review_pages": review_pages,
            "without_candidate": without_candidate,
            "estimated_cost_usd": round(len(review_pages) * REVIEW_COST_PER_PAGE_USD, 2),
        },
        "pages": pages_out,
    }
    (out / "document.md").write_text("\n\n".join(bodies), encoding="utf-8")
    (out / "REVIEW.md").write_text(review_rule(markers), encoding="utf-8")
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _ocr_one(engine: Tesseract, image_file: Path, lang: str, has_osd: bool, entry: dict) -> dict:
    """OCR one page image, rotating it first when OSD is confident."""
    result: dict = {"status": "ok"}
    if not has_osd:
        result["orientation"] = "unchecked"
    else:
        rotate, confidence = engine.orientation(image_file)
        if rotate is None:
            result["orientation"] = "unchecked"
        elif confidence is not None and confidence < ORIENTATION_MIN_CONFIDENCE:
            # Not rotated: the owner's rule says look at the page instead.
            result["orientation"] = "low_confidence"
            result["orientation_confidence"] = confidence
        else:
            result["orientation"] = "checked"
            result["orientation_confidence"] = confidence
            if rotate % 360:
                # Saved rotated, so the reviewer looks at the picture OCR saw.
                _rotate_file(image_file, rotate)
                entry["rotation_applied"] = rotate
    try:
        result["text"] = engine.ocr(image_file, lang)
    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        result["status"] = "failed"
        result["error"] = str(e)[:300]
    return result


# --- the way back -------------------------------------------------------------------

def _split_document(text: str) -> dict[int, str]:
    parts = _ANCHOR.split(text)
    if parts[0].strip():
        raise ReviewError("document.md has text before the first page anchor; it was edited")
    bodies: dict[int, str] = {}
    pairs = list(zip(parts[1::2], parts[2::2]))
    for i, (number, body) in enumerate(pairs):
        if i < len(pairs) - 1:
            if not body.endswith("\n\n"):
                raise ReviewError(f"document.md: page {number} lost its separator; it was edited")
            body = body[:-2]
        bodies[int(number)] = body
    return bodies


def _parse_doc_txt(text: str, source: str) -> dict[int, str]:
    found: dict[int, str] = {}
    parts = _PAGE_HEADER.split(text)
    if parts[0].strip():
        raise ReviewError(f"{source}: text before the first page header line")
    for number, body in zip(parts[1::2], parts[2::2]):
        page = int(number)
        if page in found:
            raise ReviewError(f"{source}: page {page} appears twice")
        found[page] = body
    return found


def _normalise(body: str) -> str:
    lines = [line.rstrip() for line in body.strip("\n").split("\n")]
    text = "\n".join(lines).strip("\n")
    return text + "\n" if text else ""


def read_reviewed(review_dir: str | Path) -> dict[int, str]:
    """page -> reviewed text, from reviewed/doc.txt and/or reviewed/pNNNN.txt."""
    reviewed_dir = Path(review_dir) / "reviewed"
    found: dict[int, str] = {}
    origin: dict[int, str] = {}
    doc = reviewed_dir / "doc.txt"
    if doc.is_file():
        for page, body in _parse_doc_txt(doc.read_text(encoding="utf-8-sig"), "reviewed/doc.txt").items():
            found[page], origin[page] = body, "reviewed/doc.txt"
    if reviewed_dir.is_dir():
        for file in sorted(reviewed_dir.iterdir()):
            match = _PAGE_FILE.match(file.name)
            if not match:
                continue
            page = int(match.group(1))
            if page in found:
                raise ReviewError(
                    f"page {page} is reviewed twice: in {origin[page]} and reviewed/{file.name}"
                )
            text = file.read_text(encoding="utf-8-sig")
            # A per-page file may carry its own header line; it is not text.
            text = _PAGE_HEADER.sub("", text)
            found[page], origin[page] = text, f"reviewed/{file.name}"
    return {page: _normalise(body) for page, body in found.items()}


def assemble(review_dir: str | Path, *, allow_missing: bool = False) -> str:
    """The document with every reviewed page in place of its marker."""
    review_dir = Path(review_dir)
    try:
        manifest = json.loads((review_dir / "manifest.json").read_text(encoding="utf-8"))
        document = (review_dir / "document.md").read_text(encoding="utf-8")
    except FileNotFoundError as e:
        raise ReviewError(f"{review_dir} is not a review directory: {e.filename} is missing") from e

    pages = {entry["page"]: entry for entry in manifest["pages"]}
    bodies = _split_document(document)
    if sorted(bodies) != sorted(pages):
        raise ReviewError("document.md and manifest.json disagree about the pages; one was edited")

    reviewed = read_reviewed(review_dir)
    unknown = sorted(set(reviewed) - set(pages))
    if unknown:
        raise ReviewError(f"reviewed text for pages the PDF does not have: {unknown}")
    not_sent = sorted(p for p in reviewed if not pages[p]["review"])
    if not_sent:
        raise ReviewError(
            f"reviewed text for pages that were not sent for review: {not_sent}. "
            "Their text comes from the PDF's own layer; check digits with "
            "`trimitdown render` and correct the source, not the assembly."
        )
    missing = sorted(p for p, entry in pages.items() if entry["review"] and p not in reviewed)
    if missing and not allow_missing:
        raise ReviewError(
            f"pages sent for review have no reviewed text yet: {missing}. "
            "Pass allow_missing / --allow-missing to keep their unverified text."
        )
    out = []
    for page in sorted(pages):
        out.append(reviewed[page] if page in reviewed else bodies[page])
    return "\n\n".join(out)


# --- images on demand -----------------------------------------------------------------

def parse_pages(spec: str, page_count: int) -> list[int]:
    """'5,7,10-12' -> [5, 7, 10, 11, 12]; numbers from 1."""
    pages: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not match:
            raise ValueError(f"cannot read page list {spec!r}: {part!r}")
        first = int(match.group(1))
        last = int(match.group(2) or first)
        if first < 1 or last < first or last > page_count:
            raise ValueError(f"pages {part} are outside 1-{page_count}")
        pages.extend(range(first, last + 1))
    if not pages:
        raise ValueError("no pages given")
    return sorted(set(pages))


def render_pages(pdf: str | Path, pages: str | list[int], out_dir: str | Path) -> list[Path]:
    """Write page images (source or 300 dpi render, as for review) without converting."""
    import pypdfium2

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    document = pypdfium2.PdfDocument(str(pdf))
    try:
        if isinstance(pages, str):
            pages = parse_pages(pages, len(document))
        reader = open_reference(str(pdf))
        return [page_image(document, reader, page - 1, out / _stem(page))[0] for page in pages]
    finally:
        document.close()

