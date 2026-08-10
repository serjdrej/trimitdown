"""Fail when the Scoop manifest stops matching the latest published release."""
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from update_scoop_manifest import EXE, hash_for


REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "bucket" / "trimitdown.json"
RELEASES_URL = "https://api.github.com/repos/serjdrej/trimitdown/releases?per_page=100"


def fetch_latest_published_release():
    """Read the newest non-draft release and its published SHA256SUMS.

    This is deliberately the sole network boundary. Everything below it works
    from a supplied response, so the guard can be tested without GitHub access.
    """
    request = Request(RELEASES_URL, headers={"User-Agent": "trimitdown-scoop-guard"})
    with urlopen(request, timeout=30) as response:  # nosec B310: fixed HTTPS URL
        releases = json.load(response)

    published = [
        release
        for release in releases
        if not release["draft"] and release.get("published_at") is not None
    ]
    if not published:
        return None
    release = max(published, key=lambda candidate: candidate["published_at"])
    checksums_url = next(
        (
            asset["browser_download_url"]
            for asset in release["assets"]
            if asset["name"] == "SHA256SUMS"
        ),
        None,
    )
    if checksums_url is None:
        raise RuntimeError(f"{release['tag_name']} carries no SHA256SUMS")

    with urlopen(checksums_url, timeout=30) as response:  # nosec B310: GitHub asset URL
        checksums = response.read().decode("utf-8")
    return {**release, "checksums": checksums}


def check_manifest(document, release_source):
    """Return every disagreement between a manifest and a fetched release."""
    release = release_source()
    if release is None:
        return []

    version = document["version"]
    build = document["architecture"]["64bit"]
    errors = []
    if version != release["tag_name"].removeprefix("v"):
        errors.append(
            f"manifest version {version} does not match latest published release "
            f"{release['tag_name']}"
        )

    expected_url = f"/releases/download/v{version}/{EXE}"
    if expected_url not in build["url"]:
        errors.append(
            f"manifest URL does not name version {version} and {EXE}"
        )

    digest = hash_for(release["checksums"], EXE)
    if digest is None:
        errors.append(f"{release['tag_name']} SHA256SUMS has no checksum for {EXE}")
    elif build["hash"] != digest:
        errors.append(
            f"manifest hash {build['hash']} does not match SHA256SUMS for {EXE}"
        )
    return errors


def main():
    document = json.loads(MANIFEST.read_text(encoding="utf-8"))
    try:
        errors = check_manifest(document, fetch_latest_published_release)
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        print(f"Scoop manifest guard could not inspect the published release: {error}", file=sys.stderr)
        return 1

    if errors:
        print("Scoop manifest guard failed:", file=sys.stderr)
        print(*errors, sep="\n", file=sys.stderr)
        return 1
    print("Scoop manifest matches the latest published release.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
