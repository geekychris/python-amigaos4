#!/usr/bin/env bash
# Extracts clib4 runtime files from the walkero SDK docker image so
# they can be deployed to the OS4 guest alongside a python-os4-clib4
# binary.
#
# What we ship:
#   - clib4.library         → OS4 LIBS: (loaded via OpenLibrary at boot)
#   - libc.so               → OS4 alongside the binary (PROGDIR:)
#                             — do NOT put in SOBJS: shared with newlib!
#   - libpthread.so         → alongside binary (used if Python's
#                             pthread module is linked shared, which it
#                             is with clib4's -mcrt=clib4 default)
#   - libcrypt.so, libm.so  → alongside binary (Python's stdlib pulls
#                             these transitively; safest to bundle)
#
# The important invariant: clib4's libc.so and newlib's libc.so cannot
# coexist in SOBJS:. If both are present the ELF loader picks whichever
# came first and the wrong-runtime binary crashes. Solution: each
# variant binary lives in its own drawer and looks first in PROGDIR:
# for its .so files. install-on-guest.sh sets this up.
#
# Usage: ./extract-clib4.sh [output-dir]
#
# Default output-dir is ./clib4-runtime/, and everything is dropped
# into a flat directory ready for `xdftool write` or scp to the guest.
set -euo pipefail

OUT="${1:-clib4-runtime}"
IMAGE="walkero/amigagccondocker:os4-gcc11"

mkdir -p "$OUT"

echo "=== extracting clib4 runtime from $IMAGE into $OUT/ ==="

docker run --rm -v "$(cd "$OUT" && pwd):/host" "$IMAGE" bash -c '
set -e
SDK=/opt/ppc-amigaos/ppc-amigaos/SDK/clib4
# The OS4 shared library (loaded via OpenLibrary at boot)
cp "$SDK/clib4.library" /host/
# ELF shared objects — loaded by the ELF loader when a clib4 binary
# starts up. All under $SDK/lib/*.so.
for f in libc.so libpthread.so libcrypt.so libm.so libamiga.so; do
    if [ -f "$SDK/lib/$f" ]; then
        cp "$SDK/lib/$f" /host/
    fi
done
# GCC runtime .so files that clib4 binaries pull in transitively.
GCCLIB=/opt/ppc-amigaos/ppc-amigaos/lib/clib4
for f in libstdc++.so libatomic.so libssp.so libobjc.so; do
    if [ -f "$GCCLIB/$f" ]; then
        cp "$GCCLIB/$f" /host/
    fi
done
chmod 644 /host/*
ls -la /host/
'

echo
echo "=== files ready for guest deployment ==="
ls -la "$OUT/"
echo
echo "Next steps:"
echo "  1. Deploy to guest — either via install-on-guest.sh, or manually:"
echo "       xdftool amigaos4-dev.hdf write $OUT/clib4.library clib4.library"
echo "       xdftool amigaos4-dev.hdf write $OUT/libc.so       python-os4-clib4/libc.so"
echo "       (etc — all .so files go alongside the binary, not in SOBJS:)"
echo "  2. On guest: copy DH1:clib4.library LIBS: CLONE"
echo "  3. All the .so's must live in PROGDIR: of the clib4 python-os4."
