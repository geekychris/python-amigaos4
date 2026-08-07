#!/usr/bin/env bash
# Deploy python-os4 (newlib and/or clib4 variants) to an OS4 guest
# via the amiga_mcp devbench HTTP bridge (host localhost:3000).
#
# Given a build tree that contains:
#   build-ppc-amigaos-750/python.exe         (newlib, if built)
#   build-ppc-amigaos-750-clib4/python.exe   (clib4, if built)
#   clib4-runtime/{clib4.library,libc.so,...} (from extract-clib4.sh)
#
# this script:
#   1. Copies each variant to its own drawer on the guest so their .so
#      files don't collide (newlib and clib4 both ship a libc.so).
#      - Newlib   → DH1:python-os4-newlib/python-os4
#      - Clib4    → DH1:python-os4-clib4/{python-os4,libc.so,libpthread.so,...}
#   2. Copies clib4.library → LIBS: (must be Amiga-side accessible for
#      any clib4 binary to start).
#   3. Copies the stdlib (Python-3.12.7/Lib) once to DH1:lib/ (shared
#      between variants — pure-python code doesn't care about libc).
#   4. Copies amiga.pip package to DH1:lib/amiga/.
#   5. Writes wrapper scripts DH1:pynewlib and DH1:pyclib4 so a user
#      can invoke either variant.
#
# Requires: amiga_mcp devbench REST daemon running on host localhost:3000.
# If running against an offline guest, do steps 1–5 manually via xdftool
# (see docs/CLIB4_BUILD.md for the exact recipe).
#
# Usage:
#   scripts/install-on-guest.sh              — deploy every variant present
#   scripts/install-on-guest.sh newlib       — newlib only
#   scripts/install-on-guest.sh clib4        — clib4 only
#   scripts/install-on-guest.sh --dry-run    — print what would be done
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
BRIDGE_URL="${BRIDGE_URL:-http://localhost:3000}"

variants=()
dry_run=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) dry_run=1 ;;
        newlib|clib4) variants+=("$arg") ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

if [ "${#variants[@]}" -eq 0 ]; then
    for v in newlib clib4; do
        case "$v" in
            newlib) [ -f "$REPO/build-ppc-amigaos-750/python.exe" ] && variants+=("newlib") ;;
            clib4)  [ -f "$REPO/build-ppc-amigaos-750-clib4/python.exe" ] && variants+=("clib4") ;;
        esac
    done
fi

if [ "${#variants[@]}" -eq 0 ]; then
    echo "no python.exe found in any build dir — run ./build-all.sh first" >&2
    exit 1
fi

echo "deploying variants: ${variants[*]}"
echo "bridge: $BRIDGE_URL"
[ "$dry_run" -eq 1 ] && echo "(dry-run; no files will be pushed)"
echo

_push() {
    local src="$1" dst="$2"
    if [ ! -f "$src" ]; then
        echo "  SKIP $src (not present)"
        return 0
    fi
    printf "  push %-56s → %s ... " "$src" "$dst"
    if [ "$dry_run" -eq 1 ]; then
        echo "(dry-run)"
        return 0
    fi
    local rc
    rc=$(curl -sS -o /tmp/push.out -w '%{http_code}' \
        -X POST "$BRIDGE_URL/api/transfer" \
        -H 'Content-Type: application/json' \
        -d "$(python3 -c "import json,sys; print(json.dumps({'source':sys.argv[1],'dest':sys.argv[2],'direction':'push'}))" "$src" "$dst")")
    if [ "$rc" = "200" ] && grep -q '"success":true' /tmp/push.out 2>/dev/null; then
        echo "OK"
    else
        echo "FAIL (http $rc)"
        cat /tmp/push.out
        return 1
    fi
}

_dos() {
    local cmd="$1"
    printf "  amigados %-56s ... " "$cmd"
    if [ "$dry_run" -eq 1 ]; then
        echo "(dry-run)"
        return 0
    fi
    curl -sS -X POST "$BRIDGE_URL/api/launch" \
        -H 'Content-Type: application/json' \
        -d "$(python3 -c "import json,sys; print(json.dumps({'command':sys.argv[1]}))" "$cmd")" \
        > /tmp/dos.out
    if grep -q '"status":"OK"' /tmp/dos.out; then
        echo "OK"
    else
        echo "FAIL"; cat /tmp/dos.out; return 1
    fi
}

for v in "${variants[@]}"; do
    echo "─── $v ─────────────────────────────────────────────────────"
    case "$v" in
        newlib)
            BDIR="$REPO/build-ppc-amigaos-750"
            GUEST_DIR="DH1:python-os4-newlib"
            EXE="$BDIR/python-stripped.exe"
            [ -f "$EXE" ] || EXE="$BDIR/python.exe"
            _dos "makedir $GUEST_DIR"
            _push "$EXE" "$GUEST_DIR/python-os4"
            # Newlib ships its libc.so in the SDK; the current AmigaOS
            # 4.1 SDK has it in SOBJS: already, so no extra .so needed.
            ;;
        clib4)
            BDIR="$REPO/build-ppc-amigaos-750-clib4"
            RT="$REPO/clib4-runtime"
            GUEST_DIR="DH1:python-os4-clib4"
            EXE="$BDIR/python-stripped.exe"
            [ -f "$EXE" ] || EXE="$BDIR/python.exe"
            _dos "makedir $GUEST_DIR"
            _push "$EXE" "$GUEST_DIR/python-os4"
            # Bundle .so files alongside the binary — the OS4 ELF loader
            # searches PROGDIR: before SOBJS:, so no conflict with newlib.
            for so in libc.so libpthread.so libcrypt.so libm.so \
                      libamiga.so libstdc++.so libatomic.so libssp.so; do
                _push "$RT/$so" "$GUEST_DIR/$so"
            done
            # clib4.library goes to LIBS: — required at boot for any
            # clib4 binary to start. Only one copy needed system-wide.
            _push "$RT/clib4.library" "SYS:Storage/clib4.library.new"
            _dos "copy SYS:Storage/clib4.library.new LIBS:clib4.library CLONE"
            _dos "delete SYS:Storage/clib4.library.new QUIET"
            ;;
    esac
    echo
done

# Common: stdlib + amiga.pip module — variant-independent.
echo "─── shared: stdlib + amiga.pip ─────────────────────────────"
_dos "makedir DH1:lib"
if [ -d "$REPO/build-ppc-amigaos-750/build/lib.amigaos-powerpc-3.12" ]; then
    echo "  (stdlib push not implemented in this script — use the existing"
    echo "   scripts/deploy.sh or push-lib helper; for a fresh guest, the"
    echo "   pyc.tar bundle from make_release.sh drops directly into DH1:lib)"
fi

# For the clib4 variant only: install the ssl shim as DH1:lib/ssl.py
# so `import ssl` transparently uses amiga.https (see
# amiga_bindings/amiga/compat/ssl_shim.py). Newlib builds have a real
# compiled _ssl that wins the import; this file is only needed on
# clib4, where no _ssl builtin exists.
for v in "${variants[@]}"; do
    if [ "$v" = "clib4" ]; then
        echo
        echo "─── ssl shim for clib4 (DH1:lib/ssl.py) ────────────────────"
        _push "$REPO/amiga_bindings/amiga/compat/ssl.py" "DH1:lib/ssl.py"
        _dos "makedir DH1:lib/amiga"
        _dos "makedir DH1:lib/amiga/compat"
        _push "$REPO/amiga_bindings/amiga/compat/__init__.py" \
              "DH1:lib/amiga/compat/__init__.py"
        _push "$REPO/amiga_bindings/amiga/compat/ssl_shim.py" \
              "DH1:lib/amiga/compat/ssl_shim.py"
    fi
done

# Wrapper scripts on the guest so users can invoke either variant
echo
echo "─── writing wrapper scripts ────────────────────────────────"
for v in "${variants[@]}"; do
    case "$v" in
        newlib) TMPW=/tmp/pynewlib.script; GUEST_DIR=DH1:python-os4-newlib ;;
        clib4)  TMPW=/tmp/pyclib4.script;  GUEST_DIR=DH1:python-os4-clib4  ;;
    esac
    cat > "$TMPW" <<EOF
; python-os4 launcher — $v variant (auto-generated by install-on-guest.sh)
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
$GUEST_DIR/python-os4 \$@
EOF
    _push "$TMPW" "DH1:py$v"
    _dos "protect DH1:py$v rwed"
done

echo
echo "Done."
echo "On guest, try:"
for v in "${variants[@]}"; do
    echo "  execute DH1:py$v -V              # print version"
    echo "  execute DH1:py$v DH1:smoke.py    # run diagnostic smoke"
done
