#!/usr/bin/env bash
# Cross-compile CPython 3.12 for OS4 PPC. Runs inside the walkero
# AmigaOS4 Docker image. Iterating on this script IS the phase-1
# work — every failure teaches us what shim / patch is next.
#
# Usage:
#   ./build.sh configure   — run ./configure only
#   ./build.sh make        — configure + make (partial ok)
#   ./build.sh clean       — nuke build dir
#   ./build.sh shell       — drop into an interactive Docker shell
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IMAGE="amiga-python-build:local"
SRC="Python-3.12.7"
BUILD="build-ppc-amigaos"

case "${1:-make}" in
  clean)
    rm -rf "$HERE/$BUILD"
    exit 0
    ;;
  shell)
    exec docker run --rm -it -v "$HERE:/work" -w /work "$IMAGE" bash
    ;;
esac

mkdir -p "$HERE/$BUILD"

docker run --rm -v "$HERE:/work" "$IMAGE" bash -c '
set -e
STAGE="${1:-make}"
echo "=== stage: $STAGE ==="

mkdir -p /tmp/build-ppc-amigaos
cd /tmp/build-ppc-amigaos

# Cross-compile environment. GCC toolchain from the walkero image
# lives under /opt/ppc-amigaos. Its bin/ dir has ppc-amigaos-gcc etc.
export PATH=/opt/ppc-amigaos/bin:$PATH
export CC=ppc-amigaos-gcc
export CXX=ppc-amigaos-g++
export AR=ppc-amigaos-ar
export RANLIB=ppc-amigaos-ranlib
export STRIP=ppc-amigaos-strip
# newlib-based OS4 crt + inline4 macros for classic-style API names
# Base CFLAGS - no shim include, so configures undeclared-function
# detection can distinguish "real function" from "our stub". The shim
# only gets force-included for the make phase below.
export CFLAGS_BASE="-mcrt=newlib -mhard-float -O2 -mcpu=440 -Wall -D__PPC__ -D__USE_INLINE__ -D__USE_OLD_TIMEVAL__ -DAMIGA -D_AMIGA -Dpowerpc -DSSIZE_MAX=0x7fffffff"
export CFLAGS="$CFLAGS_BASE"
export LDFLAGS="-mcrt=newlib -lauto"
# Ensure "ld" for shared extensions actually goes through the PPC GCC
# driver (so -mcrt=newlib etc. survive). LDSHARED from the environment
# is picked up by the CPython Makefile.
export LDSHARED="ppc-amigaos-gcc -shared"
export LINKCC="ppc-amigaos-gcc"
# CPython needs a native python of the same major.minor for freezing.
export PYTHON_FOR_BUILD=/usr/bin/python3.12
export PYTHONNOUSERSITE=1

if [ ! -f config.status ]; then
    # Configure copies Modules/Setup.local from the srcdir into the
    # builddir. Stash it in the srcdir before we run configure.
    cp /work/setup.local /work/'"$SRC"'/Modules/Setup.local
    # Ship our custom module sources into Modules/ so setup.local can
    # reference them by plain filename (avoids absolute-path Makefile bugs).
    cp /work/_amigamodule.c /work/'"$SRC"'/Modules/
    echo "=== configure ==="
    /work/'"$SRC"'/configure \
        --build=x86_64-unknown-linux-gnu \
        --host=powerpc-unknown-amigaos \
        --prefix=/tmp/python-amiga-install \
        --disable-shared \
        --disable-ipv6 \
        --without-ensurepip \
        --without-decimal-contextvar \
        --disable-test-modules \
        --with-build-python=$PYTHON_FOR_BUILD \
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
        ac_cv_func_getrandom=yes
fi

if [ "$STAGE" = "make" ]; then
    # Force our module-disable list to override configure default,
    # every time. Setup.local is only consulted from the build dir,
    # not from srcdir, so we overwrite it after configure runs.
    cp -f /work/setup.local Modules/Setup.local
    # Also refresh our custom module sources each make cycle.
    cp -f /work/_amigamodule.c /work/'"$SRC"'/Modules/
    # Compile our POSIX shims. Use --whole-archive around the .a
    # so every symbol gets pulled into the link unconditionally.
    ppc-amigaos-gcc $CFLAGS_BASE -c /work/amiga_shim.c -o amiga_shim.o
    ppc-amigaos-ar rcs libamiga_shim.a amiga_shim.o
    export LDFLAGS="$LDFLAGS -Wl,--whole-archive $(pwd)/libamiga_shim.a -Wl,--no-whole-archive"
    ppc-amigaos-gcc $CFLAGS_BASE -c /work/amissl_lazy.c -o amissl_lazy.o
    ppc-amigaos-ar rcs libamissl_lazy.a amissl_lazy.o
    export LDFLAGS="$LDFLAGS -Wl,--whole-archive $(pwd)/libamissl_lazy.a -Wl,--no-whole-archive"
    export CFLAGS="$CFLAGS_BASE -include /work/amiga_shim.h"
    echo "=== make ==="
    make -j$(nproc) || make -j1
    cp python /work/'"$BUILD"'/python.exe
    cp python /work/'"$BUILD"'/python
    echo "=== build complete ==="
    ls -la /work/'"$BUILD"'/python.exe
fi
' "${1:-make}"
