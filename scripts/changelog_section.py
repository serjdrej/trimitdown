"""Print the CHANGELOG.md section for a version, or refuse.

The release pipeline needs this in two places: the guard job refuses to build a
version the changelog does not describe, and the notes step puts the section
into the draft. Both call this script instead of each carrying its own copy of
the parsing -- two copies of the same logic drift apart in silence, and this
repository has already lived through that with its spec files.

Refusing an empty section is the point, not a nicety. A heading with nothing
under it produces notes that say nothing, which is the state this whole
mechanism exists to prevent.
"""
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def section(changelog, version):
    """The body under `## <version>`, up to the next second-level heading.

    Returns None when there is no such heading, and an empty string when the
    heading is there with nothing under it. The caller has to tell those apart:
    they are different mistakes and deserve different messages.
    """
    match = re.search(
        rf"^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else None


def main(argv):
    # The section is bilingual by definition, so the output is never plain
    # ASCII. Without this the console encoding decides whether it survives, and
    # on Windows it does not.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    if not 2 <= len(argv) <= 3:
        print("usage: changelog_section.py <version> [changelog]", file=sys.stderr)
        return 2
    version = argv[1]
    # The path is an argument so the refusals can be exercised end to end against
    # a changelog written for the occasion. A guarantee that can only be tested
    # by monkeypatching the module tends to be tested by asserting the patch.
    changelog = Path(argv[2]) if len(argv) == 3 else CHANGELOG
    body = section(changelog.read_text(encoding="utf-8"), version)
    if body is None:
        print(f"CHANGELOG.md has no section for {version}", file=sys.stderr)
        return 1
    if not body:
        print(f"the CHANGELOG.md section for {version} is empty", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
