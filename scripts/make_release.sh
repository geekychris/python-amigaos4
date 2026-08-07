#!/usr/bin/env bash
# scripts/make_release.sh — Build a complete AmigaOS 4 release package.
#
# Release Structure:
#   releases/python3-amigaos4-3.12.7/
#   ├── C/
#   │   └── python3                     (Stripped PowerPC ELF executable)
#   ├── SDK/
#   │   ├── include/python3.12/         (Python 3.12 C API headers + amiga_shim.h)
#   │   └── lib/                        (libpython3.12.a, libamiga_shim.a, libamissl_lazy.a)
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
#   releases/python3-amigaos4-3.12.7.lha

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

VERSION="3.12.7"
REL_NAME="python3-amigaos4-${VERSION}"
RELEASES_DIR="$REPO/releases"
STAGE_DIR="$RELEASES_DIR/$REL_NAME"

echo "=== Building Release Package: $REL_NAME ==="

# 1. Ensure executable is built and stripped
STRIPPED="$REPO/build-ppc-amigaos-750/python-stripped.exe"
[ ! -f "$STRIPPED" ] && STRIPPED="$REPO/build-ppc-amigaos/python-stripped.exe"
if [ ! -f "$STRIPPED" ]; then
    echo "Executable $STRIPPED not found. Running build and strip..."
    "$REPO/scripts/build.sh" --strip
    STRIPPED="$REPO/build-ppc-amigaos-750/python-stripped.exe"
    [ ! -f "$STRIPPED" ] && STRIPPED="$REPO/build-ppc-amigaos/python-stripped.exe"
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

# 5. Pre-install pip into site-packages and create System/python3/bin & C/pip3 launchers
echo "-> Pre-installing pip into System/python3/lib/site-packages..."
mkdir -p "$SYS_DIR/lib/site-packages"
python3 -c "import zipfile; zipfile.ZipFile('$STDLIB_SRC/ensurepip/_bundled/pip-24.2-py3-none-any.whl').extractall('$SYS_DIR/lib/site-packages')"

echo "-> Creating System/python3/bin helper tools..."
mkdir -p "$SYS_DIR/bin"
if [ -d "$REPO/bin" ]; then
    cp -r "$REPO/bin"/* "$SYS_DIR/bin/"
else
    cat << 'EOF' > "$SYS_DIR/bin/pip3"
.key ARGS/F
python3 -m pip <ARGS>
EOF
    cp -f "$SYS_DIR/bin/pip3" "$SYS_DIR/bin/pip"
fi
chmod +x "$SYS_DIR/bin"/* 2>/dev/null || true

cp -f "$SYS_DIR/bin/pip3" "$STAGE_DIR/C/pip3" 2>/dev/null || true

# 6. Copy Amiga Bindings, Examples, Docs, and License
echo "-> Copying amiga_bindings, examples, and documentation..."
mkdir -p "$SYS_DIR/amiga_bindings"
cp -r "$REPO/amiga_bindings"/* "$SYS_DIR/amiga_bindings/"

mkdir -p "$SYS_DIR/examples"
cp -r "$REPO/examples"/* "$SYS_DIR/examples/"

if [ -d "$REPO/docs" ]; then
    mkdir -p "$SYS_DIR/docs"
    cp -r "$REPO/docs"/* "$SYS_DIR/docs/"
fi

if [ -f "$REPO/tests/on_guest/smoke.py" ]; then
    echo "-> Packaging on-guest smoke test into System/python3/smoke.py..."
    cp "$REPO/tests/on_guest/smoke.py" "$SYS_DIR/smoke.py"
    mkdir -p "$SYS_DIR/tests/on_guest"
    cp -r "$REPO/tests"/* "$SYS_DIR/tests/" 2>/dev/null || true
fi

[ -f "$REPO/README.md" ] && cp "$REPO/README.md" "$STAGE_DIR/README.md" && cp "$REPO/README.md" "$SYS_DIR/README.md" && cp "$REPO/README.md" "$STAGE_DIR/readme.txt"
[ -f "$REPO/README.md.info" ] && cp "$REPO/README.md.info" "$STAGE_DIR/README.md.info"
[ -f "$REPO/LICENSE" ] && cp "$REPO/LICENSE" "$SYS_DIR/LICENSE"
[ -f "$REPO/Install-Python3" ] && cp "$REPO/Install-Python3" "$STAGE_DIR/Install-Python3"
[ -f "$REPO/Install-Python3.info" ] && cp "$REPO/Install-Python3.info" "$STAGE_DIR/Install-Python3.info"
[ -f "$REPO/autoinstall" ] && cp "$REPO/autoinstall" "$STAGE_DIR/autoinstall"

# 7. Package SDK headers and static libraries into SDK/
echo "-> Packaging SDK headers and static libraries into SDK/..."
SDK_DIR="$STAGE_DIR/SDK"
mkdir -p "$SDK_DIR/include/python3.12"
mkdir -p "$SDK_DIR/lib"

cp -r "$REPO/Python-3.12.7/Include"/* "$SDK_DIR/include/python3.12/" 2>/dev/null || true
BUILD_DIR="$REPO/build-ppc-amigaos-750"
[ ! -d "$BUILD_DIR" ] && BUILD_DIR="$REPO/build-ppc-amigaos"
if [ -f "$BUILD_DIR/pyconfig.h" ]; then
    cp "$BUILD_DIR/pyconfig.h" "$SDK_DIR/include/python3.12/"
elif [ -f "$REPO/Python-3.12.7/pyconfig.h" ]; then
    cp "$REPO/Python-3.12.7/pyconfig.h" "$SDK_DIR/include/python3.12/"
fi
cp "$REPO/amiga_shim.h" "$SDK_DIR/include/python3.12/amiga_shim.h"

if [ -f "$BUILD_DIR/libpython3.12.a" ]; then
    cp "$BUILD_DIR/libpython3.12.a" "$SDK_DIR/lib/libpython3.12.a"
    cp "$BUILD_DIR/libpython3.12.a" "$SDK_DIR/lib/libpython.a"
fi
if [ -f "$BUILD_DIR/libamiga_shim.a" ]; then
    cp "$BUILD_DIR/libamiga_shim.a" "$SDK_DIR/lib/libamiga_shim.a"
fi
if [ -f "$BUILD_DIR/libamissl_lazy.a" ]; then
    cp "$BUILD_DIR/libamissl_lazy.a" "$SDK_DIR/lib/libamissl_lazy.a"
fi

# 8. Create Startup Script Snippet
echo "-> Creating S/Package-Startup..."
mkdir -p "$SYS_DIR/S"
cat << 'EOF' > "$SYS_DIR/S/Package-Startup"
; Python 3.12 for AmigaOS 4.1
; Add these lines to your S:User-Startup:
Assign python3: SYS:System/python3
Path python3:bin ADD

; Run these commands once in a Shell to persist environment variables:
SetEnv PYTHONHOME SAVE python3:
SetEnv PYTHONPATH SAVE python3:lib;python3:lib/site-packages
EOF

# 9. Create LHA archive
cd "$RELEASES_DIR"
LHA_FILE="${REL_NAME}.lha"
echo "-> Creating LHA archive ${LHA_FILE}..."
if command -v docker >/dev/null 2>&1; then
    docker run --rm -v "$RELEASES_DIR:/work" amiga-python-build:local bash -c \
        "cd /work && lha a ${LHA_FILE} ${REL_NAME}"
else
    rm -f "${LHA_FILE}"
    lha a "${LHA_FILE}" "${REL_NAME}"
fi

echo
echo "=== Release Build Complete ==="
echo "Directory:   $STAGE_DIR"
echo "Binary:      $STAGE_DIR/C/python3 ($(wc -c < "$STAGE_DIR/C/python3" | tr -d ' ') bytes)"
echo "Lib tree:    $SYS_DIR/lib"
echo "SDK:         $SDK_DIR"
if [ -f "$RELEASES_DIR/${LHA_FILE}" ]; then
    echo "LHA Package: $RELEASES_DIR/${LHA_FILE} ($(wc -c < "$RELEASES_DIR/${LHA_FILE}" | tr -d ' ') bytes)"
fi
