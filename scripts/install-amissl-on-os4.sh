#!/usr/bin/env bash
# install-amissl-on-os4.sh — thin shell wrapper around the Python
# installer.  Runs `install_amissl_on_os4.py` next to it.  Passes
# environment through so AMISSL_TAG, AMISSL_CACHE, MCP_URL etc work.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$HERE/install_amissl_on_os4.py" "$@"
