#!/usr/bin/env bash
# Cross-compile CPython 3.12 for AmigaOS 4 PPC (PowerPC 750 baseline).
# Based on geekychris/python-amigaos4 enhancements branch.
#
# Usage:
#   ./build-750.sh configure
#   ./build-750.sh make
#   ./build-750.sh clean
#   ./build-750.sh shell
#
# Env:
#   MCRT   — target C runtime: newlib (default) or clib4.
#            Sets -mcrt=$MCRT in both CFLAGS and LDFLAGS. Also picks the
#            output directory: build-ppc-amigaos-750 for newlib (legacy
#            path preserved for compat), build-ppc-amigaos-750-clib4
#            for clib4. Build script for both variants at once:
#                MCRT=newlib ./build-750.sh && MCRT=clib4 ./build-750.sh
#            or use ./build-all.sh.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="amiga-python-build:local"
SRC="Python-3.12.7"

MCRT="${MCRT:-newlib}"
case "$MCRT" in
  newlib) BUILD="build-ppc-amigaos-750" ;;   # legacy path — backwards compat
  clib4)  BUILD="build-ppc-amigaos-750-clib4" ;;
  clib2)  BUILD="build-ppc-amigaos-750-clib2" ;;
  *) echo "unknown MCRT=$MCRT (want newlib|clib4|clib2)" >&2; exit 1 ;;
esac
echo "MCRT=$MCRT  BUILD=$BUILD"

case "${1:-make}" in
  clean)
    rm -rf "$HERE/$BUILD"
    if [ "$MCRT" = "newlib" ]; then
      rm -rf "$HERE/build-ppc-amigaos"
    fi
    exit 0
    ;;
  shell)
    if command -v docker >/dev/null 2>&1; then
      exec docker run --rm -it -v "$HERE:/work" -w /work "$IMAGE" bash
    else
      echo "Docker not found; dropping into host bash shell"
      exec bash
    fi
    ;;
esac

mkdir -p "$HERE/$BUILD"

run_build_steps() {
    STAGE="${1:-make}"
    WORK_DIR="$2"
    BUILD_DIR="$3"

    echo "=== stage: $STAGE ==="
    mkdir -p "$BUILD_DIR"
    cd "$BUILD_DIR"

    export PATH=/opt/ppc-amigaos/bin:$PATH
    export CC=ppc-amigaos-gcc
    export CXX=ppc-amigaos-g++
    export AR=ppc-amigaos-ar
    export RANLIB=ppc-amigaos-ranlib
    export STRIP=ppc-amigaos-strip

    # PowerPC 750 is a suitable common G3/G4-era AmigaOS 4 baseline.
    # GCC supplies its native AmigaOS gthread implementation through -athread=native at link time.
    export CFLAGS_BASE="-mcrt=$MCRT -mhard-float -O2 -mcpu=750 -mno-altivec -mno-powerpc64 -Wall -D__PPC__ -D__USE_INLINE__ -D__USE_OLD_TIMEVAL__ -DAMIGA -D_AMIGA -Dpowerpc -DSSIZE_MAX=0x7fffffff"
    export CFLAGS="$CFLAGS_BASE"
    export LDFLAGS="-mcrt=$MCRT -mcpu=750 -mno-altivec -mno-powerpc64 -athread=native -lauto"

    export LDSHARED="ppc-amigaos-gcc -shared"
    export LINKCC="ppc-amigaos-gcc"
    export PYTHON_FOR_BUILD="$(which python3.12 2>/dev/null || which python3)"
    export PYTHONNOUSERSITE=1

    if [ ! -f config.status ]; then
        cp "$WORK_DIR/setup.local" "$WORK_DIR/$SRC/Modules/Setup.local"
        cp "$WORK_DIR/_amigamodule.c" "$WORK_DIR/$SRC/Modules/"

        echo "=== configure ==="
        "$WORK_DIR/$SRC/configure" \
            --build=x86_64-unknown-linux-gnu \
            --host=powerpc-unknown-amigaos \
            --prefix=/tmp/python-amiga-install \
            --disable-shared \
            --disable-ipv6 \
            --without-ensurepip \
            --without-decimal-contextvar \
            --disable-test-modules \
            --with-build-python="$PYTHON_FOR_BUILD" \
            ac_cv_file__dev_ptmx=no \
            ac_cv_file__dev_ptc=no \
            ac_cv_func_dlopen=no \
            ac_cv_func_fork=no \
            ac_cv_func_getpid=yes \
            ac_cv_func_kill=no \
            ac_cv_func_epoll_create=no \
            ac_cv_func_kqueue=no \
            ac_cv_func_pipe=no \
            ac_cv_func_execv=no \
            ac_cv_have_working_getgrgid_r=no \
            ac_cv_have_working_getpwuid_r=no \
            ac_cv_func_getrandom=yes \
            ac_cv_member_struct_tm_tm_zone=no \
            ac_cv_member_struct_tm_tm_gmtoff=no
    fi

    if [ "$STAGE" = "make" ]; then
        cp -f "$WORK_DIR/setup.local" Modules/Setup.local
        cp -f "$WORK_DIR/_amigamodule.c" "$WORK_DIR/$SRC/Modules/"

        SHIM_SRC="$WORK_DIR/amiga_shim.c"
        if [ ! -f "$SHIM_SRC" ] && [ -f "$WORK_DIR/amiga_shim_fixed.c" ]; then
            SHIM_SRC="$WORK_DIR/amiga_shim_fixed.c"
        fi

        ppc-amigaos-gcc $CFLAGS_BASE -c "$SHIM_SRC" -o amiga_shim.o
        ppc-amigaos-ar rcs libamiga_shim.a amiga_shim.o
        ppc-amigaos-ranlib libamiga_shim.a
        export LDFLAGS="$LDFLAGS -Wl,--whole-archive $(pwd)/libamiga_shim.a -Wl,--no-whole-archive"

        ppc-amigaos-gcc $CFLAGS_BASE -c "$WORK_DIR/amissl_lazy.c" -o amissl_lazy.o
        ppc-amigaos-ar rcs libamissl_lazy.a amissl_lazy.o
        ppc-amigaos-ranlib libamissl_lazy.a
        export LDFLAGS="$LDFLAGS -Wl,--whole-archive $(pwd)/libamissl_lazy.a -Wl,--no-whole-archive"

        export CFLAGS="$CFLAGS_BASE -include $WORK_DIR/amiga_shim.h"

        echo "=== make ==="
        make -j$(nproc 2>/dev/null || echo 2) || make -j1

        cp python "$WORK_DIR/$BUILD/python.exe" 2>/dev/null || true
        cp python "$WORK_DIR/$BUILD/python" 2>/dev/null || true
        cp libamiga_shim.a "$WORK_DIR/$BUILD/" 2>/dev/null || true
        cp libamissl_lazy.a "$WORK_DIR/$BUILD/" 2>/dev/null || true

        # Also populate build-ppc-amigaos so release script picks up output
        # (legacy path — only for newlib builds to avoid clobbering).
        if [ "$MCRT" = "newlib" ]; then
            mkdir -p "$WORK_DIR/build-ppc-amigaos"
            cp python "$WORK_DIR/build-ppc-amigaos/python.exe" 2>/dev/null || true
            cp python "$WORK_DIR/build-ppc-amigaos/python" 2>/dev/null || true
            cp libamiga_shim.a "$WORK_DIR/build-ppc-amigaos/" 2>/dev/null || true
            cp libamissl_lazy.a "$WORK_DIR/build-ppc-amigaos/" 2>/dev/null || true
            if [ -f "libpython3.12.a" ]; then
                cp libpython3.12.a "$WORK_DIR/build-ppc-amigaos/" 2>/dev/null || true
            fi
            if [ -f "pyconfig.h" ]; then
                cp pyconfig.h "$WORK_DIR/build-ppc-amigaos/" 2>/dev/null || true
            fi
        fi

        echo "=== build complete ==="
        ls -la "$WORK_DIR/$BUILD/python.exe" "$WORK_DIR/$BUILD/libamiga_shim.a" "$WORK_DIR/$BUILD/libamissl_lazy.a"
    fi
}

if command -v docker >/dev/null 2>&1; then
    docker run --rm -v "$HERE:/work" "$IMAGE" bash -c "
    export SRC='$SRC'
    export MCRT='$MCRT'
    export BUILD='$BUILD'
    $(declare -f run_build_steps)
    run_build_steps '${1:-make}' '/work' '/work/$BUILD'
    "
else
    run_build_steps "${1:-make}" "$HERE" "$HERE/$BUILD"
fi
