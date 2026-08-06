#!/usr/bin/env bash
# scripts/build.sh — build python-os4 (thin wrapper around ../build.sh).
#
# Usage:
#   scripts/build.sh           — full make (configure if needed)
#   scripts/build.sh clean     — nuke build tree
#   scripts/build.sh shell     — drop into shell
#   scripts/build.sh --strip   — build + immediately strip
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

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

if [ "$strip_after" -eq 1 ] && [ "$mode" != "clean" ] && [ "$mode" != "shell" ]; then
    echo
    echo "=== stripping build-ppc-amigaos/python.exe -> python-stripped.exe ==="
    if command -v docker >/dev/null 2>&1; then
        docker run --rm \
            -v "$REPO:/work" \
            -w /work/build-ppc-amigaos \
            amiga-python-build:local \
            bash -c 'export PATH=/opt/ppc-amigaos/bin:$PATH; \
                     ppc-amigaos-strip -o python-stripped.exe python.exe && \
                     ls -la python-stripped.exe'
    else
        export PATH=/opt/ppc-amigaos/bin:$PATH
        ppc-amigaos-strip -o "$REPO/build-ppc-amigaos/python-stripped.exe" "$REPO/build-ppc-amigaos/python.exe"
        ls -la "$REPO/build-ppc-amigaos/python-stripped.exe"
    fi
fi

echo
echo "Next: scripts/make_release.sh"
