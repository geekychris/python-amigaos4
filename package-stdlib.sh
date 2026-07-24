#!/usr/bin/env bash
# Package a slim CPython stdlib as python312.zip for on-Amiga import.
#
# CPython's zipimport lets a single .zip on sys.path substitute for the
# unpacked Lib/ tree. Much better fit for OS4 than 372 individual .py
# files pushed one at a time over the ~14 KB/s serial bridge.
#
# Deploy to the Amiga with:
#   amiga_push_file(local=./python312.zip, amiga=DH1:python312.zip)
#   setenv PYTHONHOME  DH1:                (on the OS4 side)
#   setenv PYTHONPATH  DH1:python312.zip
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/Python-3.12.7/Lib"
OUT="$HERE/python312.zip"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

if [ ! -d "$SRC" ]; then
    echo "error: $SRC not found - extract Python-3.12.7.tar.xz first" >&2
    exit 1
fi

echo "=== copying Lib/ ==="
cp -r "$SRC" "$WORK/pylib"

echo "=== slimming ==="
# Everything below cuts things we can't run on OS4 or don't need for
# Phase 2. Add back per-module as later phases unlock more of the OS.
cd "$WORK/pylib"
rm -rf test idlelib turtledemo tkinter venv ensurepip \
       distutils multiprocessing asyncio unittest pydoc_data \
       lib2to3 dbm sqlite3 ctypes xml curses email
find . -type d -name tests       -exec rm -rf {} + 2>/dev/null || true
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rm -f turtle.py

echo "=== packing ==="
rm -f "$OUT"
( cd "$WORK/pylib" && zip -qr9 "$OUT" . )

ls -la "$OUT"
echo ""
echo "done. transfer via bridge:"
echo "  amiga_push_file $OUT DH1:python312.zip"
