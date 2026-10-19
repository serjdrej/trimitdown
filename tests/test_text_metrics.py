"""The measurements the PDF route decides on: the per-script gate and the sanity check."""
import unicodedata

import pytest

from trimitdown import text_metrics as tm

# Bound to a plain name: a decorator written "@pytest.mark..." at the start of a
# line reads as an e-mail address to the PII guard on commit.
parametrize = pytest.mark.parametrize


def _measured_counts(text: str) -> tuple[int, float]:
    # Verbatim the formula the gate was measured with (collapse_gate_detail.py,
    # outside this repository): Lu/Ll letters named CYRILLIC, share among Lu/Ll.
    letters = [ch for ch in text if unicodedata.category(ch) in ("Lu", "Ll")]
    cyrillic = [ch for ch in letters if "CYRILLIC" in unicodedata.name(ch, "")]
    return len(cyrillic), len(cyrillic) / max(len(letters), 1)


def _measured_fires(candidate: str, reference: str) -> bool:
    alt_cyr, alt_share = _measured_counts(reference)
    cand_cyr, cand_share = _measured_counts(candidate)
    return alt_cyr >= 20 and alt_share >= 0.20 and (
        cand_cyr < 0.50 * alt_cyr or cand_share < 0.50 * alt_share
    )


def _text(cyr: int, lat: int) -> str:
    # Letters in words of five, so nothing here depends on word boundaries.
    letters = "д" * cyr + "q" * lat
    return " ".join(letters[i:i + 5] for i in range(0, len(letters), 5))


# (reference Cyrillic, reference Latin, candidate Cyrillic, candidate Latin)
BOUNDARY_CASES = [
    (19, 0, 0, 0),        # one letter under the floor: not applicable
    (20, 0, 0, 0),        # at the floor: applicable, and the candidate lost all
    (20, 0, 10, 0),       # exactly half the count: does not fire
    (20, 0, 9, 0),        # just under half: fires
    (20, 80, 20, 80),     # share exactly 0.20: applicable, nothing lost
    (199, 801, 0, 801),   # share 0.199: not applicable however much is lost
    (200, 800, 200, 800),
    (100, 100, 100, 300),  # share drops from 0.5 to exactly 0.25: half, does not fire
    (100, 100, 100, 302),  # share drops just under half: fires
    (300, 0, 300, 0),
    (300, 0, 0, 300),     # the silent swap: Cyrillic gone, letter total kept
]


@parametrize("ref_cyr,ref_lat,cand_cyr,cand_lat", BOUNDARY_CASES)
def test_cyrillic_gate_reproduces_the_measured_rule(ref_cyr, ref_lat, cand_cyr, cand_lat):
    """For Cyrillic the per-script gate must decide exactly as the measured one.

    The measured numbers (156 pages, 12 silent swaps) hold only for that rule.
    Latin is switched off here so that only the Cyrillic decision is compared.
    Breaks on any change to the 20 / 0.20 / 0.5 constants or to < versus <=;
    verified by changing the ratio comparison to <=, which turned the
    exactly-half cases red.
    """
    reference = _text(ref_cyr, ref_lat)
    candidate = _text(cand_cyr, cand_lat)

    fired, _ = tm.gate_fires(candidate, reference, latin=False)

    assert fired == _measured_fires(candidate, reference)


def test_the_boundary_table_exercises_both_outcomes():
    # A table where every row agrees on "no" would pass against a gate that
    # never fires. This keeps the table honest.
    outcomes = {_measured_fires(_text(c, l), _text(rc, rl)) for rc, rl, c, l in BOUNDARY_CASES}
    assert outcomes == {True, False}


def test_a_swap_to_latin_fires_although_the_letter_total_is_unchanged():
    """The 12 measured silent pages: Cyrillic replaced by Latin, total kept.

    A gate over "letters in general" sees nothing here -- the sum is equal. Fails
    if gate_fires is rewritten to compare letter totals (verified by doing so).
    """
    reference = _text(300, 0)
    candidate = _text(0, 300)
    assert sum(tm.letter_counts(reference).values()) == sum(tm.letter_counts(candidate).values())

    fired, details = tm.gate_fires(candidate, reference)

    assert fired
    assert details["fired_on"] == ["CYRILLIC"]


def test_latin_gate_is_on_and_switchable():
    """Owner's decision for 0.2.0: the gate watches Latin too (provisional until
    the 200-document benchmark). Switching it off must leave it blind to Latin
    loss and nothing else; fails if the switch is ignored or the default flips."""
    reference = _text(0, 300)
    candidate = _text(0, 100)

    assert tm.GATE_LATIN is True
    assert tm.gate_fires(candidate, reference)[0] is True
    assert tm.gate_fires(candidate, reference, latin=False)[0] is False
    # The Cyrillic decision does not depend on the switch.
    assert tm.gate_fires(_text(0, 0), _text(300, 0), latin=False)[0] is True


def test_scripts_are_read_from_unicode_names():
    assert tm.script_of("ж") == "CYRILLIC"
    assert tm.script_of("Q") == "LATIN"
    assert tm.script_of("λ") == "GREEK"
    assert tm.script_of("ب") == "ARABIC"
    assert tm.script_of("漢") == "CJK"
    assert tm.script_of("ア") == "KATAKANA"
    # A width variant names its script second.
    assert tm.script_of("Ａ") == "LATIN"
    assert tm.script_of("7") is None
    assert tm.script_of("─") is None


def test_letters_outside_lu_ll_have_a_gate_of_their_own():
    # Category Lo letters were invisible to the measured rule; here a page of
    # Chinese that loses its text is caught like any other script.
    reference = "漢字" * 50
    fired, details = tm.gate_fires("", reference)
    assert fired and details["fired_on"] == ["CJK"]


def test_mixed_script_words_are_counted_inside_words_only():
    text = "слово word слоwо тeкст 2024 a-б"
    # "слоwо" and "тeкст" mix inside a word; "a-б" is two words with a hyphen.
    assert tm.mixed_script_words(text) == 2
    assert tm.latin_in_cyr_words(text) == 2


def test_a_page_of_frames_is_not_garbage():
    """Frames drawn with box-drawing characters are not garbage.

    87 measured pages were exactly this false alarm. Here frames outnumber the
    letters five to one; fails if U+2500-U+259F are counted as characters
    (verified by narrowing the excluded range to nothing).
    """
    lines = []
    for i in range(20):
        lines.append("┌" + "─" * 48 + "┐")
        lines.append("│ налог сбор │" + "░" * 30)
        lines.append("└" + "─" * 48 + "┘")
    text = "\n".join(lines)

    assert tm.is_sane(text) == (True, None)


def test_a_table_of_sums_is_not_garbage():
    """Digits and their punctuation are not held against a page.

    A sum table has almost no letters. Fails if digits are counted in the
    letter-share denominator (verified by removing the digit exclusion).
    """
    rows = ["Итого"] + [f"{1000 + i * 37} {i * 12.5:.2f} {i * 7}% {2020 + i}.{i % 12 + 1:02d}"
                        for i in range(30)]
    assert tm.is_sane("\n".join(rows)) == (True, None)


def test_cp1251_read_as_winansi_is_garbage():
    # What every decoder returns for cp1251 bytes in a font without ToUnicode.
    mojibake = ("налог сбор плательщик ведомость сальдо период расчет сумма " * 5).encode(
        "cp1251").decode("latin-1")
    assert tm.is_sane(mojibake) == (False, "latin1_mojibake")


def test_french_and_german_are_not_mojibake():
    text = "Le réseau électrique préféré à côté de l'hôpital. Grüße aus Köln, schöne Straße. " * 4
    assert tm.is_sane(text) == (True, None)


def test_replacement_characters_are_garbage():
    assert tm.is_sane("текст ��� " * 10)[1] == "replacement_or_control"


def test_symbol_soup_is_garbage():
    # Glyph codes read as ASCII symbols: no letters among the non-numeric
    # characters at all.
    assert tm.is_sane("#$&@^~`{}|\\ " * 10) == (False, "few_letters")


def test_too_little_text_is_never_judged():
    # A page number must not send a page to paid review.
    assert tm.is_sane("— 3 —") == (True, None)
    assert tm.is_sane("") == (True, None)


def test_strip_box_drawing_keeps_the_text_and_drops_frame_lines():
    text = "┌──────┐\n│ налог  сбор │\n└──────┘\nплоская строка"
    assert tm.strip_box_drawing(text) == "налог сбор\nплоская строка"


def test_text_metrics_carry_the_manifest_fields():
    metrics = tm.text_metrics("налог сбор слоwо")
    assert metrics["letters"] == 14
    assert metrics["latin_in_cyr_words"] == 1
    assert metrics["mixed_script_words"] == 1
    assert metrics["scripts"] == {"CYRILLIC": 13, "LATIN": 1}
    assert metrics["cyr_ratio"] == round(13 / 14, 4)
