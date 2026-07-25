#!/usr/bin/env bash
# scripts/build.sh — build python-os4 (thin wrapper around ../build.sh).
#
# Delegates to the top-level build.sh which runs the walkero Docker
# image, configures + makes CPython 3.12 with our _amiga native
# module + POSIX shim layer.  Strips into build-ppc-amigaos/python-stripped.exe
# ready for deploy.sh to push.
#
# Usage:
#   scripts/build.sh           — full make (configure if needed)
#   scripts/build.sh clean     — nuke build tree
#   scripts/build.sh shell     — drop into an interactive Docker shell
#   scripts/build.sh --strip   — build + immediately strip
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

# Which mode?  Default = make.  --strip adds a final strip pass.
strip_after=0
mode=make
for arg in "$@"; do
    case "$arg" in
        --strip) strip_after=1 ;;
        clean|shell|configure|make) mode="$arg" ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

cd "$REPO"
./build.sh "$mode"

# Only strip if user asked, and only after make/configure not shell/clean.
if [ "$strip_after" -eq 1 ] && [ "$mode" != "clean" ] && [ "$mode" != "shell" ]; then
    echo
    echo "=== stripping build-ppc-amigaos/python.exe -> python-stripped.exe ==="
    docker run --rm \
        -v "$REPO:/work" \
        -w /work/build-ppc-amigaos \
        amiga-python-build:local \
        bash -c 'export PATH=/opt/ppc-amigaos/bin:$PATH; \
                 ppc-amigaos-strip -o python-stripped.exe python.exe && \
                 ls -la python-stripped.exe'
fi

echo
echo "Next: scripts/deploy.sh"
