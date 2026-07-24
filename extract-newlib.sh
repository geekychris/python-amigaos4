#!/usr/bin/env bash
# Extracts newlib.library from the walkero SDK Docker image so it can
# be deployed to OS4:LIBS/newlib.library. The version we link against
# must match (or be older than) what's on the Amiga side, otherwise
# the ELF loader refuses with "requires newlib.library".
#
# Usage: ./extract-newlib.sh [output-path]
set -euo pipefail
OUT="${1:-newlib.library}"
IMAGE="walkero/amigagccondocker:os4-gcc11-arm64"
docker run --rm -v "$(pwd):/host" "$IMAGE" \
    cp /opt/ppc-amigaos/ppc-amigaos/SDK/newlib/lib/libc.so "/host/$OUT"
chmod 644 "$OUT"
echo "extracted $(ls -la "$OUT")"
echo ""
echo "Next: deploy $OUT to the OS4 side and copy into LIBS: with"
echo "  copy DH1:$OUT LIBS: CLONE"
