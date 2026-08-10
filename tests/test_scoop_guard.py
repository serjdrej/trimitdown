"""The Scoop channel must name the latest published desktop build."""
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "bucket" / "trimitdown.json"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_scoop_manifest import check_manifest  # noqa: E402


WINDOWS_ARTIFACT = "TrimItDown-windows-x64.exe"
RELEASE_VERSION = "0.1.2"
RELEASE_HASH = "4f4901ff2f107dcf3d80863868b10f432c4bc5a8c69212133045ad6b54481ee9"


def current_manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def published_release():
    """A complete stand-in for the published-release network result."""
    return {
        "tag_name": f"v{RELEASE_VERSION}",
        "draft": False,
        "assets": [
            {"name": "SHA256SUMS"},
            {"name": WINDOWS_ARTIFACT},
        ],
        "checksums": f"{RELEASE_HASH}  {WINDOWS_ARTIFACT}\n",
    }


def test_rejects_a_manifest_behind_the_latest_published_release():
    # Removing the release-version comparison would let an old Scoop package
    # survive after publication, the outage this guard exists to expose.
    document = current_manifest()
    document["version"] = "0.1.1"
    document["architecture"]["64bit"]["url"] = document["architecture"]["64bit"][
        "url"
    ].replace("v0.1.2", "v0.1.1")

    errors = check_manifest(document, published_release)

    assert errors == [
        "manifest version 0.1.1 does not match latest published release v0.1.2"
    ]


def test_rejects_a_manifest_ahead_of_the_latest_published_release():
    # Removing the same comparison would approve a manifest pointing at a tag
    # which is absent or still draft, leaving users with a broken download URL.
    document = current_manifest()
    document["version"] = "0.1.3"
    document["architecture"]["64bit"]["url"] = document["architecture"]["64bit"][
        "url"
    ].replace("v0.1.2", "v0.1.3")

    errors = check_manifest(document, published_release)

    assert errors == [
        "manifest version 0.1.3 does not match latest published release v0.1.2"
    ]


def test_rejects_a_manifest_hash_that_differs_from_sha256sums():
    # Removing the checksum comparison would approve a hand-edited hash even
    # while the release version still looks correct in review.
    document = current_manifest()
    document["architecture"]["64bit"]["hash"] = "f" * 64

    errors = check_manifest(document, published_release)

    assert errors == [
        f"manifest hash {'f' * 64} does not match SHA256SUMS for {WINDOWS_ARTIFACT}"
    ]


def test_rejects_a_manifest_url_that_does_not_name_its_version():
    # Removing the URL check would make Scoop request a different release than
    # the version displayed in the manifest.
    document = current_manifest()
    document["architecture"]["64bit"]["url"] = document["architecture"]["64bit"][
        "url"
    ].replace("v0.1.2", "v0.1.1")

    errors = check_manifest(document, published_release)

    assert errors == [
        "manifest URL does not name version 0.1.2 and TrimItDown-windows-x64.exe"
    ]
