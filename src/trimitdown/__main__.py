"""`python -m trimitdown`: the same command as the `trimitdown` console script.

A reviewer or a skill whose environment has the package but not its scripts
directory on PATH still has this route, and the review rule names it. In the
paid review run on 2026-10-20 neither reviewer could make a full-resolution
crop because `trimitdown` was not on PATH and nothing else was named.
"""
import sys

from trimitdown.cli import main

sys.exit(main())
