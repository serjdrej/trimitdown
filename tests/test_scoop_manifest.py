"""The scoop manifest: the one measured-working channel for an unsigned build.

Measured, not assumed: installing through scoop leaves no Mark-of-the-Web on the
executable, so SmartScreen does not stand between a user and the app. winget
refuses unsigned installers outright. Until there is a certificate, this is the
channel that works.
"""
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "bucket" / "trimitdown.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from update_scoop_manifest import hash_for, retarget  # noqa: E402

# The name the release pipeline actually attaches. A manifest naming something
# else downloads a 404, and the failure lands on a user rather than on us.
WINDOWS_ARTIFACT = "TrimItDown-windows-x64.exe"


def manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_the_manifest_is_valid_json_with_the_fields_scoop_requires():
    document = manifest()

    assert document["version"]
    assert document["homepage"] == "https://github.com/serjdrej/trimitdown"
    assert document["license"] == "MIT"
    assert "64bit" in document["architecture"]


def test_the_url_the_hash_and_the_version_agree():
    # These three move together at every publication. Two of them updated and one
    # forgotten is an install that fails on a hash mismatch for every user at
    # once, which is why a command does it rather than a person.
    document = manifest()
    build = document["architecture"]["64bit"]

    assert f"/releases/download/v{document['version']}/" in build["url"]
    assert WINDOWS_ARTIFACT in build["url"]
    assert re.fullmatch(r"[0-9a-f]{64}", build["hash"]), (
        "the hash is not a sha256 digest"
    )


def test_the_manifest_does_not_put_the_app_on_the_path():
    """Adding ``bin`` here must fail this test.

    Windows resolves PATH case-insensitively, and the pip package installs a
    console command called `trimitdown`. A shim for the windowed build under the
    same name would shadow it, so someone with both installed would type
    `trimitdown convert file.pdf` and get a GUI window and no output. The first
    throwaway manifest used for the Mark-of-the-Web measurement did exactly that.

    A desktop application belongs in the Start menu, which is what `shortcuts`
    is for.
    """
    document = manifest()

    assert "bin" not in document, (
        "a shim would shadow the pip CLI of the same name on a case-insensitive PATH"
    )
    assert document["shortcuts"] == [["TrimItDown.exe", "TrimItDown"]]


def test_autoupdate_reads_the_checksums_we_publish():
    # Without this scoop's own updater re-downloads and re-hashes, which proves
    # the network worked and nothing else. Our SHA256SUMS is the record of what
    # was actually published.
    autoupdate = manifest()["autoupdate"]

    assert autoupdate["hash"]["url"].endswith("/SHA256SUMS")
    assert "$version" in autoupdate["architecture"]["64bit"]["url"]
    assert "$version" in autoupdate["hash"]["url"]


def test_hash_for_picks_the_right_line():
    checksums = (
        "aaaa  TrimItDown-macOS-arm64.dmg\n"
        f"{'b' * 64}  {WINDOWS_ARTIFACT}\n"
        "cccc  TrimItDown-macOS-x86_64.dmg\n"
    )

    assert hash_for(checksums, WINDOWS_ARTIFACT) == "b" * 64
    assert hash_for(checksums, "TrimItDown-windows-arm64.exe") is None


def test_hash_for_does_not_match_a_name_that_merely_ends_the_same():
    # `sha256sum` output is `<digest>  <name>`, and a substring match would take
    # a line for OldTrimItDown-windows-x64.exe as ours.
    checksums = f"{'d' * 64}  Old{WINDOWS_ARTIFACT}\n"

    assert hash_for(checksums, WINDOWS_ARTIFACT) is None


def test_hash_for_reads_the_binary_marker_sha256sum_writes():
    # `sha256sum -b` prefixes the name with an asterisk. Reading that as part of
    # the filename would silently find nothing.
    checksums = f"{'e' * 64} *{WINDOWS_ARTIFACT}\n"

    assert hash_for(checksums, WINDOWS_ARTIFACT) == "e" * 64


def test_retarget_moves_all_three_fields_together():
    before = MANIFEST_PATH.read_text(encoding="utf-8")

    after = retarget(before, "9.9.9", "f" * 64)
    document = json.loads(after)

    assert document["version"] == "9.9.9"
    assert "/releases/download/v9.9.9/" in document["architecture"]["64bit"]["url"]
    assert document["architecture"]["64bit"]["hash"] == "f" * 64
    # The autoupdate block keeps its placeholder: it is a template for scoop's
    # own tooling, not a second copy of the current version.
    assert "$version" in document["autoupdate"]["architecture"]["64bit"]["url"]


def test_retarget_changes_nothing_else():
    before = MANIFEST_PATH.read_text(encoding="utf-8")
    document = json.loads(before)

    after = json.loads(retarget(before, "9.9.9", "f" * 64))

    for field in ("description", "homepage", "license", "shortcuts", "checkver"):
        assert after[field] == document[field]
