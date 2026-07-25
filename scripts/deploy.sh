#!/usr/bin/env bash
# scripts/deploy.sh — push python-os4 + amiga_bindings + examples to
# a running OS4 target (via the amiga-devbench bridge).
#
# Assumes:
#   * QEMU sam460ex is up (see amiga_mcp/scripts/start-qemu-os4.sh)
#   * amiga-bridge daemon is running on the target
#   * `mcp-cli` or equivalent is available and points at devbench,
#     OR run the individual `amiga_transfer` / `amiga_push_file`
#     tool calls from a Claude Code session that has the amiga-dev MCP.
#
# For the "just run this by hand from a Claude session" case we print
# the exact tool invocations to stdout — safe to copy/paste.
#
# Usage:
#   scripts/deploy.sh                 — deploy binary + bindings + examples
#   scripts/deploy.sh --binary-only   — just push python-os4
#   scripts/deploy.sh --code-only     — bindings + examples, skip binary
#   scripts/deploy.sh --stdlib        — also push the pure-Python stdlib files
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

binary=1
code=1
stdlib=0
for arg in "$@"; do
    case "$arg" in
        --binary-only) code=0 ;;
        --code-only)   binary=0 ;;
        --stdlib)      stdlib=1 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) echo "unknown arg: $arg" >&2; exit 1 ;;
    esac
done

STRIPPED="$REPO/build-ppc-amigaos/python-stripped.exe"
if [ "$binary" -eq 1 ] && [ ! -f "$STRIPPED" ]; then
    echo "ERROR: $STRIPPED not found — run scripts/build.sh --strip first" >&2
    exit 1
fi

cat <<'BANNER'
====================================================================
 python-amigaos4 deploy recipe
====================================================================
 Paste each block into a Claude Code session with the amiga-dev MCP
 server connected (or drive the same calls from another MCP client).
BANNER
echo

if [ "$binary" -eq 1 ]; then
    echo "--- binary ($(wc -c < "$STRIPPED" | tr -d ' ') bytes) ---"
    cat <<EOF
amiga_push_file(
  local_path="$STRIPPED",
  amiga_path="DH1:python-os4")
EOF
    echo
fi

if [ "$code" -eq 1 ]; then
    echo "--- amiga_bindings package tree ---"
    cat <<EOF
amiga_dos_command("makedir DH1:pytests/amiga_bindings/amiga/{bridge,dos,exec,intuition,os,pip,turtle}")

amiga_transfer(
  source="$REPO/amiga_bindings/amiga/*.py",
  dest="DH1:pytests/amiga_bindings/amiga/")
EOF
    for sub in bridge dos exec intuition os pip turtle; do
        cat <<EOF
amiga_transfer(
  source="$REPO/amiga_bindings/amiga/$sub/*.py",
  dest="DH1:pytests/amiga_bindings/amiga/$sub/")
EOF
    done
    echo
    echo "--- examples ---"
    cat <<EOF
amiga_dos_command("makedir DH1:pytests/examples")

amiga_transfer(
  source="$REPO/examples/*.py",
  dest="DH1:pytests/examples/")
EOF
    echo
    echo "--- tests ---"
    cat <<EOF
amiga_dos_command("makedir DH1:pytests/{language,stdlib,io,amiga}")

amiga_push_file(
  local_path="$REPO/tests/framework.py",
  amiga_path="DH1:pytests/framework.py")

for sub in language stdlib io amiga; do
    amiga_transfer(
      source="$REPO/tests/\$sub/*.py",
      dest="DH1:pytests/\$sub/")
done
EOF
    echo
fi

if [ "$stdlib" -eq 1 ]; then
    echo "--- stdlib flat files (one-time, per new OS4 image) ---"
    STDLIB="$REPO/Python-3.12.7/Lib"
    cat <<EOF
amiga_dos_command("makedir DH1:lib DH1:lib/encodings DH1:lib/collections \\
                    DH1:lib/importlib DH1:lib/json DH1:lib/re DH1:lib/http \\
                    DH1:lib/email DH1:lib/logging DH1:lib/urllib \\
                    DH1:lib/concurrent DH1:lib/concurrent/futures \\
                    DH1:lib/zipfile DH1:lib/zipfile/_path \\
                    DH1:lib/ensurepip DH1:lib/ensurepip/_bundled")

amiga_transfer(source="$STDLIB/*.py",              dest="DH1:lib/")
amiga_transfer(source="$STDLIB/encodings/*.py",    dest="DH1:lib/encodings/")
amiga_transfer(source="$STDLIB/collections/*.py",  dest="DH1:lib/collections/")
amiga_transfer(source="$STDLIB/importlib/*.py",    dest="DH1:lib/importlib/")
amiga_transfer(source="$STDLIB/json/*.py",         dest="DH1:lib/json/")
amiga_transfer(source="$STDLIB/re/*.py",           dest="DH1:lib/re/")
amiga_transfer(source="$STDLIB/http/*.py",         dest="DH1:lib/http/")
amiga_transfer(source="$STDLIB/email/*.py",        dest="DH1:lib/email/")
amiga_transfer(source="$STDLIB/logging/*.py",      dest="DH1:lib/logging/")
amiga_transfer(source="$STDLIB/urllib/*.py",       dest="DH1:lib/urllib/")
amiga_transfer(source="$STDLIB/concurrent/*.py",   dest="DH1:lib/concurrent/")
amiga_transfer(source="$STDLIB/concurrent/futures/*.py",
               dest="DH1:lib/concurrent/futures/")
amiga_transfer(source="$STDLIB/zipfile/*.py",      dest="DH1:lib/zipfile/")
amiga_transfer(source="$STDLIB/zipfile/_path/*.py", dest="DH1:lib/zipfile/_path/")
amiga_transfer(source="$STDLIB/ensurepip/*.py",    dest="DH1:lib/ensurepip/")
amiga_push_file(
  local_path="$STDLIB/ensurepip/_bundled/pip-24.2-py3-none-any.whl",
  amiga_path="DH1:lib/ensurepip/_bundled/pip-24.2-py3-none-any.whl")

# python312.zip broken with our port's zipimport — rename out.
amiga_dos_command("if exists DH1:lib/python312.zip \\
                     rename DH1:lib/python312.zip DH1:lib/python312.zip.bak \\
                   endif")
EOF
    echo
fi

cat <<'FOOTER'

--- once deployed, set env vars ONCE per boot (see docs/RUNNING.md) ---
amiga_dos_command("setenv PYTHONHOME DH1: ; setenv PYTHONPATH DH1:lib")

--- sanity check ---
amiga_dos_command("DH1:python-os4 --version")
   -> Python 3.12.7

amiga_dos_command("DH1:python-os4 RAM:tiny.py")
   -> hello world
      argv: ['RAM:tiny.py']

--- run a demo (see docs/DEMOS.md for the full gallery) ---
amiga_dos_command("DH1:python-os4 DH1:pytests/examples/clock.py")
FOOTER
