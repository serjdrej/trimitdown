"""Cheap text measurements the PDF route decides on. Standard library only.

Three things live here:

* the per-script loss gate -- has the candidate text lost a script the
  reference text has plenty of;
* the sanity detector -- is a text garbage regardless of what anything else
  says about it;
* the mixed-script word counts written into the review manifest.

The gate was measured on Cyrillic only (the private set: 156 pages, of them 12
silent swaps where Cyrillic came back as Latin with the total letter count
almost unchanged). Counting "letters in general" would lose exactly those 12:
the sum barely moves. So the gate is counted per script, and for CYRILLIC it
reproduces the measured rule exactly -- see test_text_metrics.py, which pins it
against the original formula.
"""
import re
import unicodedata

# The measured gate. Applicable to a script S when the reference has at least
# GATE_MIN_LETTERS letters of S making at least GATE_MIN_SHARE of its letters;
# fires when the candidate keeps less than GATE_RATIO of either.
GATE_MIN_LETTERS = 20
GATE_MIN_SHARE = 0.20
GATE_RATIO = 0.5

# Whether the gate also watches Latin. On by the owner's decision for 0.2.0, and
# provisional: the gate was never measured on Latin pages, and if pdf-inspector
# loses Latin letters inside tables or columns, every such page is substituted
# with plain text and loses its structure. The 200-document benchmark decides
# the final value; switching it off leaves the Cyrillic gate untouched.
GATE_LATIN = True

# Box drawing (U+2500-U+257F) and block elements (U+2580-U+259F). Form frames
# are drawn with them; they carry no information and must not make a page look
# like garbage -- 87 measured pages were exactly that false alarm.
_BOX_RANGE = (0x2500, 0x259F)

# Sanity thresholds. None of these is measured yet; they are deliberately loose,
# because a false "corrupt" sends a readable page to paid review, and the route
# only calls a page corrupt when every decoder agrees.
SANE_MIN_SAMPLE = 20          # fewer judged characters than this: too little to say
SANE_MAX_BAD_SHARE = 0.05     # U+FFFD, private use, control characters
SANE_MAX_LATIN1_SHARE = 0.30  # letters from À-ÿ among all letters: cp1251/KOI8 read as WinAnsi
SANE_MAX_MIXED_WORDS = 0.20   # words whose letters come from two or more scripts
SANE_MIN_WORDS = 5
SANE_MIN_LETTER_SHARE = 0.20  # letters among the characters that are not digits or punctuation

# Characters that legitimately dominate a numeric page. Digits and these are not
# counted against the letter share: a table of sums is not garbage.
_NUMERIC_PUNCTUATION = set(".,:;-–—()[]%/+№'\"«»*=<>")

_WORD = re.compile(r"[^\W\d_]+")

# Width variants name their script second ("FULLWIDTH LATIN CAPITAL LETTER A").
# Modifier and mathematical letters are deliberately left as scripts of their
# own: the measured gate counted only Lu/Ll letters named CYRILLIC, and folding
# "MODIFIER LETTER CYRILLIC ..." into CYRILLIC would move it off that rule.
_PREFIXES_TO_SKIP = {"FULLWIDTH", "HALFWIDTH"}


def is_letter(ch: str) -> bool:
    return unicodedata.category(ch).startswith("L")


def script_of(ch: str) -> str | None:
    """The script of a letter, as the first word of its Unicode name.

    CYRILLIC, LATIN, GREEK, ARABIC, HEBREW, CJK, HIRAGANA, HANGUL... Not a
    letter (category L*) -> None.
    """
    if not is_letter(ch):
        return None
    words = unicodedata.name(ch, "").split()
    if len(words) > 1 and words[0] in _PREFIXES_TO_SKIP:
        words = words[1:]
    return words[0] if words else None


def letter_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ch in text:
        script = script_of(ch)
        if script is not None:
            counts[script] = counts.get(script, 0) + 1
    return counts


def gate_fires(candidate: str, reference: str, *, latin: bool | None = None) -> tuple[bool, dict]:
    """The per-script loss gate.

    For every script S the reference has at least 20 letters of, making at least
    20 % of its letters: fire if the candidate has fewer than half as many
    letters of S, or half the share. Returns (fired, details).
    """
    latin = GATE_LATIN if latin is None else latin
    ref = letter_counts(reference)
    cand = letter_counts(candidate)
    ref_total = sum(ref.values())
    cand_total = sum(cand.values())
    checked, fired_on = [], []
    for script, count in sorted(ref.items()):
        if script == "LATIN" and not latin:
            continue
        share = count / max(ref_total, 1)
        if count < GATE_MIN_LETTERS or share < GATE_MIN_SHARE:
            continue
        checked.append(script)
        cand_count = cand.get(script, 0)
        cand_share = cand_count / max(cand_total, 1)
        if cand_count < GATE_RATIO * count or cand_share < GATE_RATIO * share:
            fired_on.append(script)
    return bool(fired_on), {"scripts_checked": checked, "fired_on": fired_on}


def words(text: str) -> list[str]:
    """Runs of letters with nothing between them: 'слово', 'word', 'слоwо'."""
    return _WORD.findall(text)


def mixed_script_words(text: str) -> int:
    """Words whose letters come from two or more scripts."""
    return sum(1 for word in words(text) if len({script_of(ch) for ch in word}) > 1)


def latin_in_cyr_words(text: str) -> int:
    """Words that mix Latin and Cyrillic letters -- the owner's check on a
    reviewed file, kept under its original name for that session's manifest."""
    count = 0
    for word in words(text):
        scripts = {script_of(ch) for ch in word}
        if "LATIN" in scripts and "CYRILLIC" in scripts:
            count += 1
    return count


def _is_box(ch: str) -> bool:
    return _BOX_RANGE[0] <= ord(ch) <= _BOX_RANGE[1]


def strip_box_drawing(text: str) -> str:
    """Remove box-drawing frames from plain text.

    Lines made of frame characters only disappear; inside a line the frame
    characters go and the spaces they leave collapse to one. Lines without any
    frame character are returned untouched.
    """
    out = []
    for line in text.split("\n"):
        if not any(_is_box(ch) for ch in line):
            out.append(line)
            continue
        cleaned = "".join(ch for ch in line if not _is_box(ch))
        cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
        if cleaned:
            out.append(cleaned)
    return "\n".join(out)


def is_sane(text: str) -> tuple[bool, str | None]:
    """Is this text plausibly text? (sane, reason it is not)

    Any one condition is enough to call it garbage:
      * more than 5 % of characters are U+FFFD, private-use or control;
      * more than 30 % of letters are Latin-1 Supplement (À-ÿ): Cyrillic bytes
        read through a Western code page;
      * more than 20 % of words mix scripts inside the word;
      * letters are under 20 % of the characters that are neither digits nor
        common punctuation (box drawing excluded too).
    A text with fewer than 20 judged characters is sane by default: too little
    to tell, and calling it garbage would send a page number to paid review.
    """
    chars = [ch for ch in text if not ch.isspace() and not _is_box(ch)]
    if len(chars) < SANE_MIN_SAMPLE:
        return True, None

    bad = sum(
        1 for ch in chars
        if ch == "�" or unicodedata.category(ch) in ("Co", "Cc", "Cs")
    )
    if bad / len(chars) > SANE_MAX_BAD_SHARE:
        return False, "replacement_or_control"

    letters = [ch for ch in chars if is_letter(ch)]
    if len(letters) >= SANE_MIN_SAMPLE:
        latin1 = sum(1 for ch in letters if 0xC0 <= ord(ch) <= 0xFF and ch not in "×÷")
        if latin1 / len(letters) > SANE_MAX_LATIN1_SHARE:
            return False, "latin1_mojibake"

    all_words = words(text)
    if len(all_words) >= SANE_MIN_WORDS:
        if mixed_script_words(text) / len(all_words) > SANE_MAX_MIXED_WORDS:
            return False, "mixed_scripts"

    judged = [ch for ch in chars if not ch.isdigit() and ch not in _NUMERIC_PUNCTUATION]
    if len(judged) >= SANE_MIN_SAMPLE and len(letters) / len(judged) < SANE_MIN_LETTER_SHARE:
        return False, "few_letters"

    return True, None


def text_metrics(text: str) -> dict:
    """The per-page numbers written into the review manifest."""
    counts = letter_counts(text)
    letters = sum(counts.values())
    return {
        "chars": sum(1 for ch in text if not ch.isspace()),
        "letters": letters,
        "cyr_ratio": round(counts.get("CYRILLIC", 0) / letters, 4) if letters else 0.0,
        "latin_in_cyr_words": latin_in_cyr_words(text),
        "mixed_script_words": mixed_script_words(text),
        "scripts": dict(sorted(counts.items())),
    }
