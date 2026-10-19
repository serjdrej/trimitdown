"""Synthetic PDFs for the 0.2 PDF route: pdf-inspector plus per-page checks.

pdf_fixtures.py writes through a single WinAnsi Helvetica and can only say
Latin-1. The route has to be exercised on Cyrillic, on box-drawing frames, on
scans with and without an OCR layer and on a silent alphabet swap, so this
module has its own small object builder with three fonts:

  F1  Helvetica, WinAnsi                        plain Latin
  FC  Helvetica, WinAnsi + a ToUnicode CMap     codes 0xC0-0xFF read as cp1251
      Cyrillic, 0xA8/0xB8 as YO/yo, 0x80-0x8A as box drawing. The glyphs drawn
      are Latin-1 accented letters; every decoder reads the CMap, which is all a
      text-extraction test needs, and no font file has to be embedded.
  FM  Helvetica, WinAnsi, no ToUnicode          the same cp1251 bytes read as
      Latin-1: the mojibake every decoder agrees on.

Text is generated deterministically from fixed word lists. No corpus text and
nothing personal goes into these files.
"""
import zlib

_BOX = "─│┌┐└┘├┤┬┴┼"
_BOX_CODES = {ch: 0x80 + i for i, ch in enumerate(_BOX)}

CYRILLIC_WORDS = (
    "налог сбор плательщик ведомость сальдо период расчет сумма взнос обязанность "
    "орган заявление документ сведения приложение страница основание решение "
    "счет порядок срок дата номер код бюджет квартал перечень уплата"
).split()
LATIN_WORDS = (
    "invoice period balance amount payment record section schedule notice "
    "account statement summary detail number total"
).split()


def encode_cyr(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        if ch in _BOX_CODES:
            out.append(_BOX_CODES[ch])
        else:
            out += ch.encode("cp1251")
    return bytes(out)


def _hex(data: bytes) -> str:
    return "<" + data.hex().upper() + ">"


def _cmap() -> bytes:
    pairs = [(0xC0 + i, 0x0410 + i) for i in range(64)]
    pairs += [(0xA8, 0x0401), (0xB8, 0x0451)]
    pairs += [(code, ord(ch)) for ch, code in _BOX_CODES.items()]
    pairs += [(c, c) for c in range(0x20, 0x7F)]
    lines = [
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap",
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def",
        "/CMapName /Adobe-Identity-UCS def /CMapType 2 def",
        "1 begincodespacerange <00> <FF> endcodespacerange",
    ]
    for start in range(0, len(pairs), 100):
        chunk = pairs[start:start + 100]
        lines.append(f"{len(chunk)} beginbfchar")
        lines += [f"<{c:02X}> <{u:04X}>" for c, u in chunk]
        lines.append("endbfchar")
    lines += ["endcmap CMapName currentdict /CMap defineresource pop end end"]
    return "\n".join(lines).encode("ascii")


def gray_image(width: int, height: int) -> bytes:
    """8-bit grey pixels: dark horizontal bands on white, like lines of print."""
    rows = []
    for y in range(height):
        dark = (y // 4) % 3 == 0 and 8 < y < height - 8
        rows.append(bytes(30 if dark and 6 < x < width - 6 else 255 for x in range(width)))
    return b"".join(rows)


IMAGE_SIZE = (200, 260)


def build(pages: list[dict]) -> bytes:
    """Build a PDF from page dicts: {"content": str, "image": bool, "rotate": int}.

    Every page shares the three fonts above. A page with "image": True gets one
    greyscale image XObject named /Im1 (IMAGE_SIZE pixels, Flate). Content
    streams are ASCII; text goes in as hex strings made by encode_cyr.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def add_stream(entries: bytes, data: bytes) -> int:
        return add(b"<< " + entries + b" /Length " + str(len(data)).encode()
                   + b" >>\nstream\n" + data + b"\nendstream")

    catalog = add(b"")  # patched once the page tree exists
    pages_obj = add(b"")
    tounicode = add_stream(b"", _cmap())
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    fc = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding "
             b"/ToUnicode " + str(tounicode).encode() + b" 0 R >>")
    fm = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    fonts = f"/Font << /F1 {f1} 0 R /FC {fc} 0 R /FM {fm} 0 R >>".encode()

    kids = []
    for page in pages:
        resources = fonts
        if page.get("image"):
            width, height = IMAGE_SIZE
            image = add_stream(
                f"/Type /XObject /Subtype /Image /Width {width} /Height {height} "
                "/ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode".encode(),
                zlib.compress(gray_image(width, height)),
            )
            resources += f" /XObject << /Im1 {image} 0 R >>".encode()
        content = add_stream(b"", page.get("content", "").encode("ascii"))
        rotate = f" /Rotate {page['rotate']}".encode() if page.get("rotate") else b""
        kids.append(add(
            b"<< /Type /Page /Parent " + str(pages_obj).encode() + b" 0 R "
            b"/MediaBox [0 0 612 792]" + rotate + b" /Resources << " + resources + b" >> "
            b"/Contents " + str(content).encode() + b" 0 R >>"
        ))

    objects[catalog - 1] = b"<< /Type /Catalog /Pages " + str(pages_obj).encode() + b" 0 R >>"
    objects[pages_obj - 1] = (
        b"<< /Type /Pages /Kids [" + " ".join(f"{k} 0 R" for k in kids).encode()
        + b"] /Count " + str(len(kids)).encode() + b" >>"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 " + str(len(objects) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (b"trailer\n<< /Size " + str(len(objects) + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref_at).encode() + b"\n%%EOF\n")
    return bytes(out)


def _words(pool, count: int, seed: int) -> list[str]:
    # A fixed linear-congruential walk over the pool: deterministic, and no
    # random-module state shared with anything else in the suite.
    out, state = [], seed
    for _ in range(count):
        state = (state * 1103515245 + 12345) % (2 ** 31)
        out.append(pool[(state >> 8) % len(pool)])
    return out


def cyrillic_lines(n_lines: int = 20, words_per_line: int = 8, seed: int = 1) -> list[str]:
    words = _words(CYRILLIC_WORDS, n_lines * words_per_line, seed)
    return [" ".join(words[i:i + words_per_line]) for i in range(0, len(words), words_per_line)]


def latin_lines(n_lines: int = 20, words_per_line: int = 8, seed: int = 70) -> list[str]:
    words = _words(LATIN_WORDS, n_lines * words_per_line, seed)
    return [" ".join(words[i:i + words_per_line]) for i in range(0, len(words), words_per_line)]


def text_block(font: str, lines: list[str], *, x=72, top=720, step=16, size=11,
               render_mode: int | None = None, encode=encode_cyr) -> str:
    mode = f"{render_mode} Tr " if render_mode is not None else ""
    return "".join(
        f"BT {mode}/{font} {size} Tf {x} {top - i * step} Td {_hex(encode(line))} Tj ET\n"
        for i, line in enumerate(lines)
    )


FULL_PAGE_IMAGE = "q 612 0 0 792 0 0 cm /Im1 Do Q\n"


# --- page dicts --------------------------------------------------------------

def cyrillic_prose_page(seed: int = 1) -> dict:
    """Plain Cyrillic prose through a ToUnicode CMap: a page pdf-inspector reads."""
    return {"content": text_block("FC", cyrillic_lines(20, 8, seed=seed))}


def box_drawing_form_page() -> dict:
    """Cyrillic form text inside frames drawn with box-drawing characters.

    The measured shape of the 87 false "garbled" pages: the text decodes
    correctly, and pdf-inspector still flags the page suspected_garbled_text and
    returns no markdown because of the U+2500 frame characters.
    """
    lines = []
    for line in cyrillic_lines(14, 5, seed=2):
        lines += ["┌" + "─" * 30 + "┐", "│ " + line + " │", "└" + "─" * 30 + "┘"]
    return {"content": text_block("FC", lines, step=16, size=9)}


def invisible_ocr_layer_page() -> dict:
    """A FineReader-shaped scan: one full-page image, text underneath in Tr 3."""
    return {
        "image": True,
        "content": FULL_PAGE_IMAGE + text_block("FC", cyrillic_lines(18, 8, seed=3), render_mode=3),
    }


def scanned_image_page(rotate: int = 0) -> dict:
    """One full-page image and no text operators at all: a scan with no layer."""
    page = {"image": True, "content": FULL_PAGE_IMAGE}
    if rotate:
        page["rotate"] = rotate
    return page


def vector_only_page() -> dict:
    """Stroked graphics and no text: no layer, but not a blank sheet either."""
    return {"content": "100 100 400 200 re S\n120 150 m 480 150 l S\n"}


def image_over_text_page() -> dict:
    """Visible Cyrillic text with an image drawn over the lower half of it."""
    return {
        "image": True,
        "content": text_block("FC", cyrillic_lines(20, 8, seed=4))
        + "q 468 0 0 300 72 300 cm /Im1 Do Q\n",
    }


def actualtext_latin_over_cyrillic_page() -> dict:
    """Cyrillic glyphs whose marked-content /ActualText says Latin.

    pdf-inspector (and pdfium) honour ActualText and read Latin; pypdf reads the
    glyphs and gets Cyrillic. Not the mechanism behind the 12 measured silent
    pages, which is unknown, but the same observable: a page pdf-inspector
    returns without any flag, in the wrong alphabet.
    """
    cyr = cyrillic_lines(16, 6, seed=5)
    lat = latin_lines(16, 6, seed=50)
    content = "".join(
        f"/Span << /ActualText ({la}) >> BDC "
        f"BT /FC 11 Tf 72 {720 - i * 16} Td {_hex(encode_cyr(cy))} Tj ET EMC\n"
        for i, (cy, la) in enumerate(zip(cyr, lat))
    )
    return {"content": content}


def cp1251_mojibake_page() -> dict:
    """cp1251 bytes through a WinAnsi font with no ToUnicode: every decoder
    reads Latin-1 accented letters. Garbage at all of them -- the corrupt path."""
    return {"content": text_block("FM", cyrillic_lines(20, 8, seed=6))}


def blank_page() -> dict:
    return {"content": ""}


def short_cyrillic_page() -> dict:
    """Six Cyrillic letters: below the gate's 20-letter floor."""
    return {"content": text_block("FC", ["стр два"])}


def latin_prose_page() -> dict:
    return {"content": text_block("F1", latin_lines(20, 8), encode=lambda s: s.encode("latin-1"))}


def numeric_table_page() -> dict:
    """Almost all digits: a sum table under a one-word heading."""
    rows = ["Итого"] + [
        f"{1000 + i * 37:>6} {i * 12.5:>10.2f} {i * 7:>4}% {2020 + i % 5}.{i % 12 + 1:02d}"
        for i in range(30)
    ]
    return {"content": text_block("FC", rows, step=14, size=9)}


# --- documents ----------------------------------------------------------------

def one(page: dict) -> bytes:
    return build([page])


def mixed_route_document() -> bytes:
    """One page per path, in a known order (page numbers from 1):

    1 accept      Cyrillic prose
    2 substitute  box-drawing form (pdf-inspector empty, layer intact)
    3 scan        image only, no layer
    4 scan        invisible OCR layer under a full-page image
    5 corrupt     cp1251 mojibake
    6 blank       nothing on the page
    7 substitute  ActualText says Latin, glyphs are Cyrillic
    """
    return build([
        cyrillic_prose_page(),
        box_drawing_form_page(),
        scanned_image_page(),
        invisible_ocr_layer_page(),
        cp1251_mojibake_page(),
        blank_page(),
        actualtext_latin_over_cyrillic_page(),
    ])


MIXED_EXPECTED = {
    1: "accept",
    2: "substitute",
    3: "scan",
    4: "scan",
    5: "corrupt",
    6: "blank",
    7: "substitute",
}
