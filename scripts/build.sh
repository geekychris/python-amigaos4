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
if [ -f "./build-750.sh" ]; then
    ./build-750.sh "$mode"
else
    ./build.sh "$mode"
fi

if [ "$strip_after" -eq 1 ] && [ "$mode" != "clean" ] && [ "$mode" != "shell" ]; then
    echo
    # Pick the build dir that matches the MCRT variant just built.
    MCRT="${MCRT:-newlib}"
    case "$MCRT" in
      newlib) BDIR="build-ppc-amigaos-750" ;;
      clib4)  BDIR="build-ppc-amigaos-750-clib4" ;;
      clib2)  BDIR="build-ppc-amigaos-750-clib2" ;;
      *)      BDIR="build-ppc-amigaos-750" ;;
    esac
    [ ! -d "$REPO/$BDIR" ] && BDIR="build-ppc-amigaos"
    echo "=== stripping $BDIR/python.exe -> python-stripped.exe ==="
    if command -v docker >/dev/null 2>&1; then
        docker run --rm \
            -v "$REPO:/work" \
            -w "/work/$BDIR" \
            amiga-python-build:local \
            bash -c 'export PATH=/opt/ppc-amigaos/bin:$PATH; \
                     ppc-amigaos-strip -o python-stripped.exe python.exe && \
                     ls -la python-stripped.exe'
    else
        export PATH=/opt/ppc-amigaos/bin:$PATH
        ppc-amigaos-strip -o "$REPO/$BDIR/python-stripped.exe" "$REPO/$BDIR/python.exe"
        cp -f "$REPO/$BDIR/python-stripped.exe" "$REPO/build-ppc-amigaos/python-stripped.exe" 2>/dev/null || true
        ls -la "$REPO/$BDIR/python-stripped.exe"
    fi
fi

echo
echo "Next: scripts/make_release.sh"
