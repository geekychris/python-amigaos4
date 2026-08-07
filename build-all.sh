#!/usr/bin/env bash
# Build BOTH newlib and clib4 variants of python-os4 back-to-back.
#
# Output:
#   build-ppc-amigaos-750/         — newlib variant (legacy path)
#   build-ppc-amigaos-750-clib4/   — clib4 variant
#
# Usage:
#   ./build-all.sh                 — build both, keep going if one fails
#   ./build-all.sh newlib          — newlib only
#   ./build-all.sh clib4           — clib4 only
#   ./build-all.sh --strict        — abort on first failure
#
# On success each variant leaves a python.exe under its build dir; then
# ./scripts/build.sh --strip strips them (invoke with the matching MCRT
# env var to pick the right output dir).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
strict=0
variants=()

for arg in "$@"; do
    case "$arg" in
        --strict) strict=1 ;;
        newlib|clib4|clib2) variants+=("$arg") ;;
        -h|--help)
            sed -n '2,15p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

if [ "${#variants[@]}" -eq 0 ]; then
    variants=(newlib clib4)
fi

overall_rc=0
for v in "${variants[@]}"; do
    echo
    echo "============================================================"
    echo "  building variant: MCRT=$v"
    echo "============================================================"
    if MCRT="$v" "$HERE/build-750.sh" make; then
        echo "=== $v build OK ==="
    else
        rc=$?
        echo "=== $v build FAILED (rc=$rc) ==="
        overall_rc=$rc
        if [ "$strict" -eq 1 ]; then
            echo "--strict set; aborting."
            exit "$rc"
        fi
    fi
done

echo
echo "============================================================"
echo "  build-all summary"
echo "============================================================"
for v in "${variants[@]}"; do
    case "$v" in
        newlib) d="build-ppc-amigaos-750" ;;
        clib4)  d="build-ppc-amigaos-750-clib4" ;;
        clib2)  d="build-ppc-amigaos-750-clib2" ;;
    esac
    if [ -f "$HERE/$d/python.exe" ]; then
        size=$(stat -f%z "$HERE/$d/python.exe" 2>/dev/null || stat -c%s "$HERE/$d/python.exe" 2>/dev/null)
        echo "  $v: OK    $d/python.exe (${size} bytes)"
    else
        echo "  $v: MISSING  $d/python.exe not present"
    fi
done

exit "$overall_rc"
