"""`python -m trimitdown` must run the CLI.

The review rule tells a reviewer without `trimitdown` on PATH to use this route
for full-resolution crops. Without src/trimitdown/__main__.py the command fails
with "is a package and cannot be directly executed" -- deleting that file must
fail this test (verified by doing so).
"""
import subprocess
import sys


def test_python_dash_m_runs_the_cli():
    run = subprocess.run(
        [sys.executable, "-m", "trimitdown", "render", "--help"],
        capture_output=True, text=True, timeout=120,
    )

    assert run.returncode == 0, run.stderr
    assert "render" in run.stdout
