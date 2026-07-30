"""Point the scoop manifest at a published release.

The manifest carries a version, a URL and a hash, and all three have to change
together at every publication. Editing them by hand is the defect this project
has already paid for twice in the release notes, so it is a command instead.

The hash comes from the SHA256SUMS attached to the release rather than from a
fresh download: those are the checksums of the bytes that were actually
published, and re-hashing a re-download would only prove the network worked.

Refuses a draft on purpose. A manifest pointing at a draft sends every scoop
user to a URL that does not exist, and it would look correct in review.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "bucket" / "trimitdown.json"
EXE = "TrimItDown-windows-x64.exe"


def hash_for(checksums, name):
    """The digest recorded for one file in a `sha256sum` listing."""
    for line in checksums.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == name:
            return parts[0]
    return None


def retarget(manifest_text, version, digest):
    """Rewrite the version, the download URL and the hash, and nothing else.

    Text in, text out: rewriting through json.dumps would reformat the whole
    file and bury the one change that matters in a diff nobody reads.
    """
    updated = re.sub(
        r'("version":\s*")[^"]+(")', rf"\g<1>{version}\g<2>", manifest_text, count=1
    )
    updated = re.sub(
        r"(/releases/download/v)[^/]+(/" + re.escape(EXE) + ")",
        rf"\g<1>{version}\g<2>",
        updated,
        count=1,
    )
    updated = re.sub(
        r'("hash":\s*")[0-9a-f]{64}(")', rf"\g<1>{digest}\g<2>", updated, count=1
    )
    return updated


def _gh(*args):
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout


def main(argv):
    if len(argv) != 2:
        print("usage: update_scoop_manifest.py <version>", file=sys.stderr)
        return 2
    version = argv[1]
    tag = f"v{version}"

    state = json.loads(_gh("release", "view", tag, "--json", "isDraft,assets"))
    if state["isDraft"]:
        print(
            f"{tag} is still a draft. A manifest pointing at a draft sends every "
            "scoop user to a URL that does not exist.",
            file=sys.stderr,
        )
        return 1

    checksums_url = next(
        (asset["url"] for asset in state["assets"] if asset["name"] == "SHA256SUMS"),
        None,
    )
    if checksums_url is None:
        print(f"{tag} carries no SHA256SUMS", file=sys.stderr)
        return 1

    checksums = _gh("api", "--header", "Accept: application/octet-stream", checksums_url)
    digest = hash_for(checksums, EXE)
    if digest is None:
        print(f"{tag} has no checksum for {EXE}", file=sys.stderr)
        return 1

    MANIFEST.write_text(
        retarget(MANIFEST.read_text(encoding="utf-8"), version, digest),
        encoding="utf-8",
    )
    print(f"bucket/trimitdown.json now points at {tag} ({digest[:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
