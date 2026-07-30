#!/usr/bin/env bash
# Regenerates every lock in this repository, in one place.
#
# One place because the flags are load-bearing and easy to get subtly wrong:
#
#   --universal          one file has to serve macOS x86_64, macOS arm64, Windows
#                        and Linux. A resolution valid on one of them and
#                        impossible on another is the original defect: cryptography
#                        49.0.0 publishes no macOS x86_64 wheel, pip built it from
#                        source against whatever OpenSSL was on the runner, and the
#                        bundle did not start.
#   --generate-hashes    without them --require-hashes has nothing to check.
#   --only-binary        a vanished wheel becomes a loud install failure instead of
#     cryptography       a quietly source-built bundle that dies on a user's machine.
#   --no-emit-package    our own two projects cannot be hashed and are installed
#                        separately with --no-deps. Leaving them in makes the lock
#                        unusable with --require-hashes.
#   --no-header          uv otherwise writes the invocation into the file. The
#                        drift canary recompiles with --upgrade, so that line
#                        would differ every single week and the canary would fail
#                        on its own flags rather than on upstream. How to
#                        regenerate belongs here, not in the output.
#
# A second copy of this invocation drifting from the first would make the drift
# canary report movement that never happened, and nobody would trust it twice.
#
# Extra flags are forwarded to every compile. The one that matters:
#
#   ./scripts/compile-locks.sh --upgrade   raise every pin to current upstream
#   ./scripts/compile-locks.sh             keep existing pins, pick up new inputs
#
# uv treats an existing output file as a set of preferences, so without --upgrade
# a recompile reproduces what is already pinned. That is the right default when
# adding a dependency and exactly wrong when asking what upstream has done.
set -euo pipefail
cd "$(dirname "$0")/.."

compile() {
  local source="$1" output="$2"
  shift 2
  uv pip compile \
    --universal \
    --generate-hashes \
    --no-header \
    --only-binary cryptography \
    --no-emit-package trimitdown \
    --no-emit-package trimitdown-pdf \
    --output-file "$output" \
    "$@" \
    "$source"
}

compile requirements.txt requirements.lock "$@"
compile requirements-dev.txt requirements-dev.lock "$@"
compile requirements-build.in requirements-build.lock "$@"
compile mac-build/requirements-dmgbuild.in mac-build/requirements-dmgbuild.lock "$@"
