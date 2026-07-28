#!/usr/bin/env bash
# scripts/make_release.sh — Build a complete AmigaOS 4 release package.
#
# Release Structure:
#   releases/python3-amigaos4-3.12.7/
#   ├── C/
#   │   └── python3                     (Stripped PowerPC ELF executable)
#   └── System/
#       └── python3/                    (Main Python 3 files)
#           ├── lib/                    (Python 3.12.7 Standard Library)
#           ├── amiga_bindings/         (Native Amiga OS4 Python modules)
#           ├── examples/               (Demo applications)
#           ├── docs/                   (Documentation)
#           ├── README.md
#           ├── LICENSE
#           └── S/
#               └── Package-Startup     (Environment variables for S:User-Startup)
#
# Output Archives:
#   releases/python3-amigaos4-3.12.7.zip
#   releases/python3-amigaos4-3.12.7.lha (if lha tool available)

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

VERSION="3.12.7"
REL_NAME="python3-amigaos4-${VERSION}"
RELEASES_DIR="$REPO/releases"
STAGE_DIR="$RELEASES_DIR/$REL_NAME"

echo "=== Building Release Package: $REL_NAME ==="

# 1. Ensure executable is built and stripped
STRIPPED="$REPO/build-ppc-amigaos/python-stripped.exe"
if [ ! -f "$STRIPPED" ]; then
    echo "Executable $STRIPPED not found. Running build and strip..."
    "$REPO/scripts/build.sh" --strip
fi

if [ ! -f "$STRIPPED" ]; then
    echo "ERROR: Failed to produce $STRIPPED" >&2
    exit 1
fi

# 2. Clean and create stage directory
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/C"
mkdir -p "$STAGE_DIR/System/python3"

# 3. Copy executable as C/python3
echo "-> Copying executable to C/python3..."
cp -f "$STRIPPED" "$STAGE_DIR/C/python3"
chmod +x "$STAGE_DIR/C/python3"

SYS_DIR="$STAGE_DIR/System/python3"

# 4. Copy Python Standard Library into System/python3/lib
STDLIB_SRC="$REPO/Python-3.12.7/Lib"
if [ ! -d "$STDLIB_SRC" ]; then
    echo "ERROR: Python stdlib source $STDLIB_SRC not found." >&2
    exit 1
fi

echo "-> Copying Standard Library to System/python3/lib..."
mkdir -p "$SYS_DIR/lib"
cp -r "$STDLIB_SRC"/* "$SYS_DIR/lib/"

# Prune non-essential test directories to slim stdlib package
echo "-> Slimming test suites from stdlib..."
rm -rf "$SYS_DIR/lib/test"
rm -rf "$SYS_DIR/lib/idlelib/idle_test"
rm -rf "$SYS_DIR/lib/tkinter/test"
rm -rf "$SYS_DIR/lib/ctypes/test"
rm -rf "$SYS_DIR/lib/bsddb/test" 2>/dev/null || true
rm -rf "$SYS_DIR/lib/sqlite3/test"
find "$SYS_DIR/lib" -type d -name "tests" -exec rm -rf {} + 2>/dev/null || true
find "$SYS_DIR/lib" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 5. Copy Amiga Bindings
echo "-> Copying amiga_bindings to System/python3/amiga_bindings..."
mkdir -p "$SYS_DIR/amiga_bindings"
cp -r "$REPO/amiga_bindings"/* "$SYS_DIR/amiga_bindings/"

# 6. Copy Examples, Docs, and License
echo "-> Copying examples and documentation..."
mkdir -p "$SYS_DIR/examples"
cp -r "$REPO/examples"/* "$SYS_DIR/examples/"

if [ -d "$REPO/docs" ]; then
    mkdir -p "$SYS_DIR/docs"
    cp -r "$REPO/docs"/* "$SYS_DIR/docs/"
fi

[ -f "$REPO/README.md" ] && cp "$REPO/README.md" "$SYS_DIR/README.md"
[ -f "$REPO/LICENSE" ] && cp "$REPO/LICENSE" "$SYS_DIR/LICENSE"
[ -f "$REPO/install-Python3" ] && cp "$REPO/install-Python3" "$STAGE_DIR/install-Python3"

# 7. Create Startup Script Snippet
echo "-> Creating S/Package-Startup..."
mkdir -p "$SYS_DIR/S"
cat << 'EOF' > "$SYS_DIR/S/Package-Startup"
; Python 3.12 for AmigaOS 4.1
; Add this line to your S:User-Startup:
Assign python3: System:python3

; Run these commands once in a Shell to persist environment variables:
SetEnv PYTHONHOME SAVE python3:
SetEnv PYTHONPATH SAVE python3:lib
EOF

# 8. Create LHA archive using Docker's lha tool
cd "$RELEASES_DIR"
LHA_FILE="${REL_NAME}.lha"
echo "-> Creating LHA archive ${LHA_FILE} via Docker..."
docker run --rm -v "$RELEASES_DIR:/work" amiga-python-build:local bash -c \
    "cd /work && lha a ${LHA_FILE} ${REL_NAME}"

echo
echo "=== Release Build Complete ==="
echo "Directory:   $STAGE_DIR"
echo "Binary:      $STAGE_DIR/C/python3 ($(wc -c < "$STAGE_DIR/C/python3" | tr -d ' ') bytes)"
echo "Lib tree:    $SYS_DIR/lib"
if [ -f "$RELEASES_DIR/${LHA_FILE}" ]; then
    echo "LHA Package: $RELEASES_DIR/${LHA_FILE} ($(wc -c < "$RELEASES_DIR/${LHA_FILE}" | tr -d ' ') bytes)"
fi
