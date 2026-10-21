"""What a Word document carries that the Markdown will not.

anydoc turns DOCX, DOC and RTF into Markdown and, in the process, drops three
things without a word: tracked changes (a DOCX loses the deleted wording and
keeps the inserted one; a DOC or RTF prints both as live text), comments, and
headers and footers. Its document model has no place for any of them, so it
cannot be asked. For a text that gets cited that is the worst kind of failure:
a wording that was struck out reads as in force, and nothing says that a change
or a comment ever existed.

This module looks at the file itself, before anydoc, and counts. It never
converts anything. `convert.py` decides what to do with the numbers: refuse,
accept, or write one line at the top of the output.

Pure on purpose, like convert.py: no FastAPI, and `olefile` (the DOC reader) is
imported only when a DOC is inspected.

What is counted, per format, and what is not (the rules are the same in all
three so that the numbers can be compared):

* **Insertions and deletions** are maximal runs. One insertion is the text a
  reviewer typed together with the paragraph break that came with it, however
  many XML elements, runs or formatting changes it spans; the same rule Word
  uses for `Revisions.Count`. A run ends at the first character that is not
  part of the same kind of change by the same author. Moved text is a deletion
  at its source and an insertion at its target.
* **Formatting-only changes** (`w:rPrChange`, `w:pPrChange`, `w:tblPrChange` and
  the rest, `sprmCPropRMark`) are NOT counted. They leave every character of the
  text as it was, so neither a refusal nor an accepted/rejected distinction can
  change what the reader sees. Word does count them in `Revisions.Count`; a
  document with only formatting changes converts as an unchanged one.
* Tracked changes are counted in the body, footnotes, endnotes, headers and
  footers. They are not counted inside comments: a comment is omitted whole
  (and counted as such), so a change inside it cannot reach the output.
* **Comments**: `w:comment` elements, `\\annotation` groups, the entries of the
  DOC comment reference table.
* **Header/footer parts** that carry text: a DOCX header or footer part, an RTF
  `\\header*`/`\\footer*` group, a DOC header story. Parts that are empty (Word
  writes empty first-page and even-page headers into almost every file) are not
  counted. A page number is text. RTF repeats the headers for every section, so
  a many-section RTF counts more parts than the same document as DOCX; no
  attempt is made to merge identical ones.
* **Images** are not counted here: anydoc's document model carries them for all
  three formats and the count there agrees with Word on the fixtures, so
  `count_images` reads its model (see convert.py). Images inside headers,
  footers and comments are part of what is omitted with them.

Where a number cannot be known the module raises `InspectionFailed` instead of
guessing: the caller must not print a document it could not check.
"""
from __future__ import annotations

import io
import posixpath
import re
import struct
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

# The formats this module reads. ODT is refused by the caller without being
# read at all; every other format anydoc reads is outside this module's scope.
INSPECTED_FORMATS = frozenset({"docx", "doc", "rtf"})


class InspectionFailed(Exception):
    """The file could not be examined; nothing can be said about what it carries."""


@dataclass(frozen=True)
class Inspection:
    format: str
    insertions: int = 0
    deletions: int = 0
    headers_footers: int = 0
    comments: int = 0
    # Why anydoc's output would NOT be the accepted reading of this document,
    # although every change in it were accepted. Only DOCX is ever accepted at
    # all; this lists the DOCX constructs that anydoc was measured to print
    # differently from Word's "accept all" (see _DocxScan).
    accept_blockers: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return self.insertions + self.deletions > 0


def inspect(data: bytes, fmt: str) -> Inspection:
    """Count what `data`, a document of format `fmt`, carries beyond its text."""
    try:
        if fmt == "docx":
            return _inspect_docx(data)
        if fmt == "rtf":
            return _inspect_rtf(data)
        if fmt == "doc":
            return _inspect_doc(data)
    except InspectionFailed:
        raise
    except Exception as e:  # a parser meeting a file it cannot follow
        raise InspectionFailed(f"{type(e).__name__}: {e}") from e
    raise ValueError(f"not an inspected format: {fmt!r}")


# --------------------------------------------------------------------------
# Revision runs, shared by the three formats
# --------------------------------------------------------------------------

class _Runs:
    """Counts maximal runs of tracked changes in a stream of tokens.

    The scanners feed it one token per piece of content, in document order: the
    set of (kind, author) keys that piece is changed by, or the empty set for
    content that is not changed. A change that follows another with nothing
    unchanged in between continues the run; a new key inside a run counts once.
    """

    def __init__(self) -> None:
        self.insertions = 0
        self.deletions = 0
        self._open: set = set()

    def token(self, keys) -> None:
        if not keys:
            self._open = set()
            return
        for key in keys:
            if key not in self._open:
                if key[0] == "ins":
                    self.insertions += 1
                else:
                    self.deletions += 1
                self._open.add(key)

    def reset(self) -> None:
        self._open = set()


# --------------------------------------------------------------------------
# DOCX
# --------------------------------------------------------------------------

_W_NAMESPACES = frozenset({
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
})
_MAX_PART_BYTES = 256 * 1024 * 1024  # a decompression bomb is not a document

_INSERTION_TAGS = {"ins": "ins", "moveTo": "ins", "del": "del", "moveFrom": "del"}
# Elements of a run that are content: when one sits outside every change it is
# unchanged text, and ends the run of changes before it.
_CONTENT_TAGS = frozenset({
    "tab", "br", "cr", "drawing", "pict", "object", "sym", "ptab", "noBreakHyphen",
    "footnoteReference", "endnoteReference",
})


def _local(tag: str) -> str:
    if tag.startswith("{"):
        namespace, _, name = tag[1:].partition("}")
        return name if namespace in _W_NAMESPACES else f"{namespace}:{name}"
    return tag


def _attribute(element, name: str) -> str:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return ""


@dataclass
class _DocxScan:
    insertions: int = 0
    deletions: int = 0
    has_text: bool = False
    comments: int = 0
    blockers: tuple[str, ...] = ()


_BLOCK_ROW = "a deleted table row (anydoc keeps it as an empty row)"
_BLOCK_CELL = "a deleted or merged table cell (anydoc keeps the cell)"
_BLOCK_ITEM = (
    "a deleted list item (anydoc keeps an empty item that shifts the numbering)"
)
_BLOCK_MARK = (
    "a deleted paragraph break that joins two paragraphs "
    "(anydoc prints them as two)"
)


def _scan_docx_part(xml: bytes, *, count_comments: bool = False) -> _DocxScan:
    """One pass over a WordprocessingML part.

    Everything is decided from the stack of element names, so no tree is kept.
    The paragraph mark is the one awkward piece: its change lives in the
    paragraph's properties but belongs at the END of the paragraph, so it is
    remembered and fed to the run counter when the paragraph closes.
    """
    # A DOCX part has no business declaring entities. Refusing the declaration
    # outright is simpler, and safer, than configuring a parser against them.
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise InspectionFailed("the document declares XML entities")

    runs = _Runs()
    result = _DocxScan()
    blockers: list[str] = []
    stack: list[str] = []
    paragraphs: list[dict] = []  # innermost last: a text box holds paragraphs
    depth = {"ins": 0, "del": 0}

    def live_content() -> None:
        # Content that survives "accept all": outside every deletion.
        if depth["del"] == 0:
            if paragraphs:
                paragraphs[-1]["live"] = True
            if depth["ins"] == 0:
                runs.token(())

    for event, element in ElementTree.iterparse(io.BytesIO(xml), events=("start", "end")):
        name = _local(element.tag)
        if event == "start":
            parent = stack[-1] if stack else ""
            grandparent = stack[-2] if len(stack) > 1 else ""
            stack.append(name)
            if name == "p":
                paragraphs.append({"marks": [], "live": False, "numbered": False})
            elif name in _INSERTION_TAGS:
                kind = _INSERTION_TAGS[name]
                key = (kind, _attribute(element, "author"))
                if parent == "rPr" and grandparent == "pPr":
                    if paragraphs:
                        paragraphs[-1]["marks"].append(key)
                elif parent == "trPr":
                    runs.token({key})
                    if kind == "del":
                        blockers.append(_BLOCK_ROW)
                else:
                    runs.token({key})
                    depth[kind] += 1
            elif name == "numPr" and parent == "pPr":
                if paragraphs:
                    paragraphs[-1]["numbered"] = True
            elif name in ("cellDel", "cellMerge") and parent == "tcPr":
                runs.token({("del", _attribute(element, "author"))})
                blockers.append(_BLOCK_CELL)
            elif name in _CONTENT_TAGS:
                live_content()
            elif name == "comment" and count_comments:
                result.comments += 1
        else:
            stack.pop()
            if name == "t":
                if element.text:
                    live_content()
                    if element.text.strip():
                        result.has_text = True
            elif name == "p":
                paragraph = paragraphs.pop()
                marks = paragraph["marks"]
                runs.token(set(marks) if marks else ())
                if any(kind == "del" for kind, _ in marks):
                    if paragraph["numbered"]:
                        blockers.append(_BLOCK_ITEM)
                    elif paragraph["live"]:
                        blockers.append(_BLOCK_MARK)
            elif name in _INSERTION_TAGS and not (
                # the paragraph-mark and row forms did not open a depth
                (stack[-1:] == ["rPr"] and stack[-2:-1] == ["pPr"]) or stack[-1:] == ["trPr"]
            ):
                depth[_INSERTION_TAGS[name]] -= 1
            element.clear()

    result.insertions = runs.insertions
    result.deletions = runs.deletions
    result.blockers = tuple(dict.fromkeys(blockers))
    return result


def _zip_part(archive: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > _MAX_PART_BYTES:
        raise InspectionFailed(f"{name} is larger than {_MAX_PART_BYTES >> 20} MiB unpacked")
    return archive.read(info)


def _relationships(archive: zipfile.ZipFile, rels_name: str, base_dir: str) -> list[tuple[str, str]]:
    """(type suffix, normalised part name) for every internal relationship."""
    data = _zip_part(archive, rels_name)
    if data is None:
        return []
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise InspectionFailed("the document declares XML entities")
    found = []
    for _, element in ElementTree.iterparse(io.BytesIO(data), events=("end",)):
        if element.tag.rpartition("}")[2] != "Relationship":
            continue
        if element.get("TargetMode") == "External":
            continue
        kind = (element.get("Type") or "").rpartition("/")[2]
        target = element.get("Target") or ""
        if target.startswith("/"):
            part = target.lstrip("/")
        else:
            part = posixpath.normpath(posixpath.join(base_dir, target))
        found.append((kind, part))
    return found


def _inspect_docx(data: bytes) -> Inspection:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise InspectionFailed(f"not a readable zip package ({e})") from e
    with archive:
        main = next(
            (part for kind, part in _relationships(archive, "_rels/.rels", "")
             if kind == "officeDocument"),
            "word/document.xml",
        )
        main_xml = _zip_part(archive, main)
        if main_xml is None:
            raise InspectionFailed(f"the main part {main} is missing")
        related = _relationships(
            archive,
            posixpath.join(posixpath.dirname(main), "_rels", posixpath.basename(main) + ".rels"),
            posixpath.dirname(main),
        )

        insertions = deletions = headers_footers = comments = 0
        blockers: list[str] = []

        scan = _scan_docx_part(main_xml)
        insertions += scan.insertions
        deletions += scan.deletions
        blockers += scan.blockers

        seen = {main}
        for kind, part in related:
            if part in seen:
                continue
            seen.add(part)
            if kind in ("footnotes", "endnotes"):
                xml = _zip_part(archive, part)
                if xml is None:
                    continue
                scan = _scan_docx_part(xml)
                insertions += scan.insertions
                deletions += scan.deletions
                blockers += scan.blockers
            elif kind in ("header", "footer"):
                xml = _zip_part(archive, part)
                if xml is None:
                    continue
                scan = _scan_docx_part(xml)
                insertions += scan.insertions
                deletions += scan.deletions
                blockers += scan.blockers
                if scan.has_text:
                    headers_footers += 1
            elif kind == "comments":
                xml = _zip_part(archive, part)
                if xml is None:
                    continue
                comments += _scan_docx_part(xml, count_comments=True).comments

    return Inspection(
        "docx", insertions, deletions, headers_footers, comments,
        tuple(dict.fromkeys(blockers)),
    )


# --------------------------------------------------------------------------
# RTF
# --------------------------------------------------------------------------

# Destinations whose content is not document text: tables, generated list
# numbering, pictures. Skipped whole, so their words never break a run.
_RTF_SKIP = frozenset({
    "fonttbl", "colortbl", "stylesheet", "info", "listtable", "listoverridetable",
    "rsidtbl", "revtbl", "filetbl", "pgptbl", "listtext", "pntext", "pict",
    "shppict", "nonshppict", "bkmkstart", "bkmkend", "xmlnstbl", "latentstyles",
    "themedata", "colorschememapping", "datastore", "generator", "template",
    "object", "pn", "pnseclvl",
})
_RTF_HF = frozenset({
    "header", "headerl", "headerr", "headerf",
    "footer", "footerl", "footerr", "footerf",
})
_RTF_WORD = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?")


class _RtfState:
    __slots__ = ("skip", "ignorable", "first", "hf", "hf_owner", "uc", "skip_units",
                 "deleted", "revised", "author_ins", "author_del")

    def __init__(self) -> None:
        self.skip = False
        self.ignorable = False
        self.first = False
        self.hf: list | None = None  # shared [seen_text] of the enclosing header/footer
        self.hf_owner = False
        self.uc = 1
        self.skip_units = 0
        self.deleted = False
        self.revised = False
        self.author_ins = 0
        self.author_del = 0

    def child(self) -> "_RtfState":
        other = _RtfState()
        for slot in self.__slots__:
            setattr(other, slot, getattr(self, slot))
        other.first = True
        other.ignorable = False
        other.hf_owner = False
        return other


_HEX = b"0123456789abcdefABCDEF"


def _inspect_rtf(data: bytes) -> Inspection:
    runs = _Runs()
    headers_footers = comments = 0
    state = _RtfState()
    stack: list[_RtfState] = []
    n = len(data)
    i = 0

    def emit(visible: bool) -> None:
        if state.skip:
            return
        keys = set()
        if state.deleted:
            keys.add(("del", state.author_del))
        if state.revised:
            keys.add(("ins", state.author_ins))
        runs.token(keys)
        if visible and state.hf is not None:
            state.hf[0] = True

    while i < n:
        byte = data[i]
        if byte == 0x7B:  # {
            stack.append(state)
            state = state.child()
            i += 1
            continue
        if byte == 0x7D:  # }
            if state.hf_owner and state.hf and state.hf[0]:
                headers_footers += 1
            if stack:
                state = stack.pop()
            i += 1
            continue
        if byte == 0x5C:  # backslash
            if i + 1 >= n:
                break
            nxt = data[i + 1]
            if nxt == 0x27:  # \'hh
                if state.skip_units:
                    state.skip_units -= 1
                else:
                    state.first = False
                    code = int(data[i + 2: i + 4], 16) if data[i + 2: i + 4].strip(_HEX) == b"" else 0x20
                    emit(code > 0x20 and code != 0xA0)
                i += 4
                continue
            if nxt == 0x2A:  # \*
                state.ignorable = True
                i += 2
                continue
            if chr(nxt) in "\\{}~-_":
                state.skip_units = 0
                state.first = False
                emit(chr(nxt) in "\\{}~")
                i += 2
                continue
            if nxt in (0x0D, 0x0A):  # backslash-newline is a \par
                state.first = False
                emit(False)
                i += 2
                continue
            match = _RTF_WORD.match(data, i)
            if match is None:  # a control symbol this scanner has no use for
                i += 2
                continue
            word = match.group(1).decode("ascii")
            param = int(match.group(2)) if match.group(2) is not None else None
            i = match.end()
            state.skip_units = 0 if word != "u" else state.skip_units

            if state.first:
                state.first = False
                if word == "annotation":
                    if not state.skip:
                        comments += 1
                    state.skip = True
                elif state.ignorable or word in _RTF_SKIP:
                    state.skip = True
                elif word in _RTF_HF:
                    state.hf = [False]
                    state.hf_owner = True
                state.ignorable = False
                if state.skip:
                    if word == "bin" and param:
                        i += param
                    continue

            if word == "bin":
                i += max(param or 0, 0)
            elif word == "deleted":
                state.deleted = param != 0
            elif word == "revised":
                state.revised = param != 0
            elif word == "revauthdel":
                state.author_del = param or 0
            elif word == "revauth":
                state.author_ins = param or 0
            elif word == "plain":
                state.deleted = state.revised = False
            elif word == "uc":
                state.uc = param if param is not None else 1
            elif word == "u":
                char = chr((param or 0) % 65536)
                emit(char >= " " and not char.isspace())
                state.skip_units = state.uc
            elif word in ("par", "line", "tab", "sect", "page", "cell", "row",
                          "emdash", "endash", "bullet", "lquote", "rquote",
                          "ldblquote", "rdblquote", "nestcell", "nestrow"):
                emit(word in ("emdash", "endash", "bullet", "lquote", "rquote",
                              "ldblquote", "rdblquote"))
            continue

        # a plain character
        if byte in (0x0D, 0x0A):
            i += 1
            continue
        if state.skip_units:
            state.skip_units -= 1
            i += 1
            continue
        state.first = False
        emit(byte > 0x20 and byte != 0xA0)
        i += 1

    return Inspection("rtf", runs.insertions, runs.deletions, headers_footers, comments)


# --------------------------------------------------------------------------
# DOC (Word 97-2003 binary, [MS-DOC])
# --------------------------------------------------------------------------

def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


_SPRM_DEL = 0x0800       # sprmCFRMarkDel: this text is a tracked deletion
_SPRM_INS = 0x0801       # sprmCFRMark: this text is a tracked insertion
_SPRM_INS_AUTHOR = 0x4804  # sprmCIbstRMark
_SPRM_DEL_AUTHOR = 0x4863  # sprmCIbstRMarkDel
_FIB_PLCFANDREF = 4
_FIB_PLCFHDD = 11
_FIB_PLCFBTECHPX = 12
_FIB_CLX = 33


def _sprm_operand_size(opcode: int, data: bytes, offset: int) -> int:
    spra = opcode >> 13
    if spra in (0, 1):
        return 1
    if spra in (2, 4, 5):
        return 2
    if spra == 3:
        return 4
    if spra == 7:
        return 3
    return 1 + data[offset]  # spra 6: a length byte, then that many bytes


def _revision_sprms(grpprl: bytes) -> tuple[bool, bool, int, int]:
    """(inserted, deleted, insert author, delete author) of one property list."""
    inserted = deleted = False
    author_ins = author_del = 0
    i = 0
    while i + 2 <= len(grpprl):
        opcode = _u16(grpprl, i)
        i += 2
        if i >= len(grpprl):
            break
        size = _sprm_operand_size(opcode, grpprl, i)
        operand = grpprl[i + (1 if opcode >> 13 == 6 else 0): i + size]
        i += size
        if opcode == _SPRM_INS:
            inserted = bool(operand and operand[0] & 1)
        elif opcode == _SPRM_DEL:
            deleted = bool(operand and operand[0] & 1)
        elif opcode == _SPRM_INS_AUTHOR and len(operand) >= 2:
            author_ins = _u16(operand, 0)
        elif opcode == _SPRM_DEL_AUTHOR and len(operand) >= 2:
            author_del = _u16(operand, 0)
    return inserted, deleted, author_ins, author_del


class _Pieces:
    """The piece table: which file bytes hold which characters."""

    def __init__(self, word: bytes, clx: bytes) -> None:
        self.word = word
        self.prcs: list[bytes] = []
        i = 0
        while i < len(clx) and clx[i] == 1:
            size = _u16(clx, i + 1)
            self.prcs.append(clx[i + 3: i + 3 + size])
            i += 3 + size
        if i >= len(clx) or clx[i] != 2:
            raise InspectionFailed("the piece table (Clx) is not where the FIB says")
        length = _u32(clx, i + 1)
        plc = clx[i + 5: i + 5 + length]
        count = (length - 4) // 12
        self.cps = [_u32(plc, 4 * k) for k in range(count + 1)]
        self.pieces = []  # (cp_start, cp_end, byte_offset, compressed, prm)
        base = 4 * (count + 1)
        for k in range(count):
            raw = _u32(plc, base + 8 * k + 2)
            prm = _u16(plc, base + 8 * k + 6)
            compressed = bool(raw & 0x40000000)
            offset = (raw & 0x3FFFFFFF) // 2 if compressed else (raw & 0x3FFFFFFF)
            self.pieces.append((self.cps[k], self.cps[k + 1], offset, compressed, prm))

    def own_properties(self) -> list[tuple[int, int, bytes]]:
        """(first cp, end cp, property list) for pieces whose Prm points into the Clx."""
        return [
            (cp_start, cp_end, self.prcs[prm >> 1])
            for cp_start, cp_end, _, _, prm in self.pieces
            if prm & 1 and (prm >> 1) < len(self.prcs)
        ]

    def text(self, start: int, end: int) -> str:
        """Characters [start, end), decoded well enough to tell blank from not."""
        out = []
        for cp_start, cp_end, offset, compressed, _ in self.pieces:
            a, b = max(start, cp_start), min(end, cp_end)
            if a >= b:
                continue
            width = 1 if compressed else 2
            raw = self.word[offset + (a - cp_start) * width: offset + (b - cp_start) * width]
            out.append(raw.decode("cp1252" if compressed else "utf-16-le", errors="replace"))
        return "".join(out)

    def cp_ranges(self, fc_start: int, fc_end: int) -> list[tuple[int, int]]:
        """The character ranges whose bytes lie in [fc_start, fc_end)."""
        found = []
        for cp_start, cp_end, offset, compressed, _ in self.pieces:
            width = 1 if compressed else 2
            piece_end = offset + (cp_end - cp_start) * width
            a, b = max(fc_start, offset), min(fc_end, piece_end)
            if a < b:
                found.append((cp_start + (a - offset) // width, cp_start + (b - offset) // width))
        return found


def _has_visible_text(text: str) -> bool:
    """Any printable non-blank character outside a field's instruction."""
    in_instruction: list[bool] = []
    for ch in text:
        if ch == "":  # field begin: the instruction follows
            in_instruction.append(True)
        elif ch == "":  # field separator: the result follows
            if in_instruction:
                in_instruction[-1] = False
        elif ch == "":  # field end
            if in_instruction:
                in_instruction.pop()
        elif not any(in_instruction) and ch >= " " and not ch.isspace():
            return True
    return False


def _inspect_doc(data: bytes) -> Inspection:
    import olefile

    if not olefile.isOleFile(data):
        raise InspectionFailed("not an OLE compound file")
    ole = olefile.OleFileIO(data)
    try:
        if not ole.exists("WordDocument"):
            raise InspectionFailed("no WordDocument stream")
        word = ole.openstream("WordDocument").read()
        if _u16(word, 0) != 0xA5EC:
            raise InspectionFailed("the WordDocument stream has no Word signature")
        if _u16(word, 2) < 0xC1:
            raise InspectionFailed("a Word 6/95 file (before Word 97)")
        flags = _u16(word, 0x0A)
        if flags & 0x0100:
            raise InspectionFailed("the document is encrypted")
        table_name = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(table_name):
            raise InspectionFailed(f"no {table_name} stream")
        table = ole.openstream(table_name).read()

        csw = _u16(word, 0x20)
        position = 0x22 + csw * 2
        cslw = _u16(word, position)
        long_words = position + 2
        ccp_text = _u32(word, long_words + 4 * 3)
        ccp_footnotes = _u32(word, long_words + 4 * 4)
        ccp_headers = _u32(word, long_words + 4 * 5)
        ccp_comments = _u32(word, long_words + 4 * 7)
        position = long_words + cslw * 4
        pair_count = _u16(word, position)
        pairs = position + 2

        def fc_lcb(index: int) -> tuple[int, int]:
            if index >= pair_count:
                return 0, 0
            return _u32(word, pairs + 8 * index), _u32(word, pairs + 8 * index + 4)

        fc, lcb = fc_lcb(_FIB_CLX)
        if not lcb:
            raise InspectionFailed("the document has no piece table")
        pieces = _Pieces(word, table[fc: fc + lcb])

        # Comments: one entry per reference mark in the text, 4 + 34 bytes each
        # ([MS-DOC] PlcfandRef: n+1 character positions, n ATRDPre10).
        _, lcb = fc_lcb(_FIB_PLCFANDREF)
        comments = (lcb - 4) // 34 if lcb >= 4 else 0

        # Header and footer stories: the first six positions delimit the
        # separator stories of footnotes and endnotes, then six per section.
        # All are counted alike; a story with nothing printable is not a part.
        headers_footers = 0
        fc, lcb = fc_lcb(_FIB_PLCFHDD)
        header_start = ccp_text + ccp_footnotes
        if lcb and ccp_headers:
            cps = [_u32(table, fc + 4 * k) for k in range(lcb // 4)]
            for a, b in zip(cps, cps[1:]):
                a, b = max(a, 0), min(b, ccp_headers)
                if a < b and _has_visible_text(pieces.text(header_start + a, header_start + b)):
                    headers_footers += 1

        # Tracked changes: character properties in the CHPX formatted disk pages.
        marked: list[tuple[int, int, str, int]] = []  # (cp start, cp end, kind, author)

        def add(cp_ranges, props) -> None:
            inserted, deleted, author_ins, author_del = props
            for a, b in cp_ranges:
                if inserted:
                    marked.append((a, b, "ins", author_ins))
                if deleted:
                    marked.append((a, b, "del", author_del))

        fc, lcb = fc_lcb(_FIB_PLCFBTECHPX)
        if lcb >= 4:
            count = (lcb - 4) // 8
            for k in range(count):
                page = _u32(table, fc + 4 * (count + 1) + 4 * k) & 0x3FFFFF
                fkp = word[page * 512: page * 512 + 512]
                if len(fkp) < 512:
                    raise InspectionFailed("a formatted disk page lies outside the file")
                runs_in_page = fkp[511]
                for r in range(runs_in_page):
                    offset = fkp[4 * (runs_in_page + 1) + r] * 2
                    if not offset:
                        continue
                    props = _revision_sprms(fkp[offset + 1: offset + 1 + fkp[offset]])
                    if props[0] or props[1]:
                        add(pieces.cp_ranges(_u32(fkp, 4 * r), _u32(fkp, 4 * (r + 1))), props)
        # A piece can also carry its properties itself (a Prm that points at a
        # property list in the Clx; fast-saved files). The other form of Prm
        # names one of a fixed table of single sprms, none of them a revision
        # mark as far as [MS-DOC] says, so it is not read.
        for cp_start, cp_end, grpprl in pieces.own_properties():
            props = _revision_sprms(grpprl)
            if props[0] or props[1]:
                add([(cp_start, cp_end)], props)

        comment_start = header_start + ccp_headers
        runs = _Runs()
        previous_end = -1
        for a, b, kind, author in sorted(marked):
            if comment_start <= a < comment_start + ccp_comments:
                continue  # a change inside a comment: the comment is omitted whole
            if a > previous_end:
                runs.reset()  # an unchanged character lies between
            runs.token({(kind, author)})
            previous_end = max(previous_end, b)
        return Inspection("doc", runs.insertions, runs.deletions, headers_footers, comments)
    finally:
        ole.close()


# --------------------------------------------------------------------------
# Images and the one-line summary
# --------------------------------------------------------------------------

def count_images(document) -> int:
    """Images in an anydoc `Document`, in the body, tables, lists and notes."""
    total = 0

    def inlines(items) -> None:
        nonlocal total
        for item in items or ():
            if item.kind == "image":
                total += 1
            inlines(item.content)

    def block(item) -> None:
        inlines(item.content)
        if item.list is not None:
            for entry in item.list.items:
                for inner in entry.blocks:
                    block(inner)
        if item.table is not None:
            for row in item.table.grid:
                for slot in row:
                    if slot.cell is not None:
                        for inner in slot.cell.blocks:
                            block(inner)
        for inner in item.blocks or ():
            block(inner)

    for item in document.blocks:
        block(item)
    for note in document.notes:
        for item in note.blocks:
            block(item)
    return total


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def summary_phrase(report: dict) -> str:
    """'accepted 1 insertion, 1 deletion; omitted 2 header/footer parts, 1 comment'.

    Built from the report so the note at the top of the Markdown, the line on
    stderr and the JSON can never disagree. Empty when there is nothing to say.
    """
    parts = []
    changes = report.get("tracked_changes") or {}
    if changes.get("accepted"):
        said = []
        if changes["insertions"]:
            said.append(_plural(changes["insertions"], "insertion"))
        if changes["deletions"]:
            said.append(_plural(changes["deletions"], "deletion"))
        if said:
            parts.append("accepted " + ", ".join(said))
    omitted = report.get("omitted") or {}
    said = []
    if omitted.get("headers_footers"):
        said.append(_plural(omitted["headers_footers"], "header/footer part"))
    if omitted.get("comments"):
        said.append(_plural(omitted["comments"], "comment"))
    if omitted.get("images"):
        said.append(_plural(omitted["images"], "image"))
    if said:
        parts.append("omitted " + ", ".join(said))
    return "; ".join(parts)
