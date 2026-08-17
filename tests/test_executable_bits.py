"""Repository-index checks for files that are meant to be run."""

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_shebang_files_are_executable_in_the_git_index():
    """A shebang means the tracked file is intended to be run as a program.

    The index, rather than the working-tree permission, is the portable source
    of truth. Windows does not retain the executable bit on disk, but it does
    retain the mode recorded by Git and can therefore catch this regression.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "-s", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise AssertionError(
            "git is required to verify executable bits recorded in the index"
        ) from error

    assert result.returncode == 0, (
        "git ls-files -s failed; this test requires a Git working tree so it "
        "can verify executable bits recorded in the index"
    )

    missing_executable_bit = []
    for record in result.stdout.split(b"\0"):
        if not record:
            continue
        metadata, path_bytes = record.split(b"\t", maxsplit=1)
        mode, _object_id, _stage = metadata.split()
        path = os.fsdecode(path_bytes)
        with (REPO_ROOT / path).open("rb") as tracked_file:
            first_line = tracked_file.readline()
        if not first_line.startswith(b"#!"):
            continue
        if mode != b"100755":
            missing_executable_bit.append((path, mode.decode("ascii")))

    assert not missing_executable_bit, "\n".join(
        f"{path} begins with a shebang but is not executable in the git index "
        f"(mode {mode}); fix it with: git update-index --chmod=+x {path}"
        for path, mode in missing_executable_bit
    )
