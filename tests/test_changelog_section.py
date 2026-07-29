"""The changelog parser the release pipeline builds its notes from."""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "changelog_section.py"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from changelog_section import section  # noqa: E402

CHANGELOG = """# Changelog

Preamble that belongs to no version.

## 1.2.0

### Что изменилось

- вторая версия

### What changed

- the second version

## 1.1.0

- the first version
"""


def test_section_stops_at_the_next_version():
    # A section that runs on into the next one puts the previous release's notes
    # into this release's draft, and the draft is what a human approves.
    body = section(CHANGELOG, "1.2.0")
    assert "the second version" in body
    assert "the first version" not in body
    assert "## 1.1.0" not in body


def test_section_keeps_both_languages():
    # The notes are a deliberately bilingual artifact. A parser that took only
    # the first sub-heading would silently ship half of them.
    body = section(CHANGELOG, "1.2.0")
    assert "### Что изменилось" in body
    assert "### What changed" in body


def test_section_excludes_the_preamble():
    body = section(CHANGELOG, "1.1.0")
    assert "Preamble" not in body


def test_section_is_none_when_the_version_is_absent():
    assert section(CHANGELOG, "9.9.9") is None


def test_section_is_empty_rather_than_none_when_the_heading_has_no_body():
    # Two different mistakes: nobody wrote the section, or somebody left the
    # heading behind. The caller refuses both but has to say which.
    assert section("## 1.0.0\n\n## 0.9.0\n\n- text\n", "1.0.0") == ""


def test_a_version_number_is_not_matched_inside_a_longer_one():
    changelog = "## 1.2.10\n\n- ten\n"
    assert section(changelog, "1.2.1") is None


def _run(version, changelog=None):
    command = [sys.executable, str(SCRIPT), version]
    if changelog is not None:
        command.append(str(changelog))
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8")


def test_the_script_prints_the_section_of_the_shipping_changelog():
    from trimitdown import __version__

    result = _run(__version__)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_the_script_refuses_a_version_the_changelog_does_not_describe():
    # This exit status is what stops a release from being built. If it ever
    # returns 0, the guard job passes and the draft gets notes with no
    # description of the changes -- which is the state this exists to prevent.
    result = _run("99.99.99")
    assert result.returncode == 1
    assert "99.99.99" in result.stderr
    # The message, not just the status. A missing section and an empty one are
    # different mistakes with different remedies -- write it, or fill it in --
    # and the message is the only thing that tells a person which they have.
    # Asserting the status alone leaves that distinction unprotected: measured,
    # the whole file stayed green with the missing-section branch removed.
    assert "no section" in result.stderr


def test_the_script_refuses_a_heading_with_nothing_under_it(tmp_path):
    # A heading someone left behind produces notes with no description of the
    # changes -- the exact outcome this mechanism exists to prevent, arriving
    # through the door marked "the section is there".
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## 1.0.0\n\n## 0.9.0\n\n- text\n", encoding="utf-8")

    result = _run("1.0.0", changelog)
    assert result.returncode == 1
    assert "empty" in result.stderr


def test_the_script_prints_the_section_it_was_pointed_at(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("## 1.0.0\n\n- a described change\n", encoding="utf-8")

    result = _run("1.0.0", changelog)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "- a described change"
