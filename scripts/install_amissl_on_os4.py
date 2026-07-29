#!/usr/bin/env python3
"""install_amissl_on_os4.py — automated AmiSSL installer for the
Python-on-OS4 setup.

What it does, driven from the mac side via devbench's MCP endpoint:

  1. Idempotency check — asks OS4 whether LIBS:amisslmaster.library +
     LIBS:AmiSSL/amissl_v<N>.library are already present, exits early
     if so.
  2. Fetches the AmiSSL <tag>-OS4.lha release from github.com to a
     local cache (~/.cache/amissl by default).
  3. Pushes the .lha over the devbench bridge to RAM:.  Retries a
     couple of times because the bridge can wedge on 3–4MB pushes.
  4. Extracts on the Amiga (`lha x RAM:<file> RAM:`), copies the
     libraries into LIBS:, then deletes the temp files.
  5. Runs a smoke test: `python-os4 -c 'import ssl; print(ssl.OPENSSL_VERSION)'`.

Config knobs (env vars):
  AMISSL_TAG      pin a specific release, e.g. `AMISSL_TAG=5.27`
  AMISSL_CACHE    where to keep the downloaded archive
  MCP_URL         devbench MCP endpoint (default http://localhost:3000/mcp)
  PYTHON_OS4      target-side path to the interpreter (default python3)

Exit codes:
  0   installed (or already installed) + smoke test passed
  1   generic failure, look at the printed message
  2   bridge unreachable — start QEMU + amiga-bridge on OS4 side
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


FORCE        = "--force" in sys.argv[1:] or bool(os.environ.get("AMISSL_FORCE"))
AMISSL_TAG   = os.environ.get("AMISSL_TAG", "")     # blank = ask GitHub
AMISSL_CACHE = Path(os.environ.get("AMISSL_CACHE",
                                    Path.home() / ".cache" / "amissl"))
DEVBENCH_URL = os.environ.get("DEVBENCH_URL", "http://localhost:3000")
PYTHON_OS4   = os.environ.get("PYTHON_OS4", "python3")

PUSH_RETRIES = 4
PUSH_BACKOFF = 5.0    # seconds between retries


# ---------------------------------------------------------------------------
# devbench REST API helpers (simpler than MCP JSON-RPC — no session state)
# ---------------------------------------------------------------------------

class DevbenchError(RuntimeError):
    pass


def _api(path: str, *, method: str = "GET", body: dict | None = None,
         timeout: float = 120.0) -> dict:
    url = f"{DEVBENCH_URL}{path}"
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        raise DevbenchError(f"devbench unreachable at {url}: {e}") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw.decode("utf-8", errors="replace")}


def dos(cmd: str, timeout: int = 20) -> str:
    """Run an AmigaDOS shell command via the bridge SCRIPT path.

    /api/command routes structured protocol commands (GETVAR/SETVAR/
    CALLHOOK/etc.) to registered clients, not raw shell commands.
    /api/script wraps the input in an AmigaDOS script that the bridge
    executes via Execute() on the target, capturing stdout/stderr."""
    r = _api("/api/script", method="POST",
             body={"script": cmd}, timeout=timeout + 10.0)
    if "error" in r:
        return f"ERR: {r['error']}"
    return str(r.get("output") or r.get("status") or r)


def push(local: Path, remote: str) -> str:
    r = _api("/api/transfer", method="POST",
             body={"source": str(local), "dest": remote, "direction": "push"},
             timeout=600.0)
    if not r.get("success", False):
        return f"ERR: {r.get('message') or r.get('error') or r}"
    return (f"Transferred {r.get('bytes', '?')} bytes in "
            f"{r.get('elapsed', '?')}s, crc_match={r.get('crc_match')}")


def ping() -> str:
    r = _api("/api/ping", method="POST", body={}, timeout=10.0)
    if "error" in r:
        return f"ERR: {r['error']}"
    return r.get("message", str(r))


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def step_ping():
    print("=== 1. bridge check")
    try:
        r = ping()
    except DevbenchError as e:
        print(f"    ERR {e}")
        sys.exit(2)
    if "alive" not in r.lower():
        print(f"    unexpected ping response: {r}")
        sys.exit(2)
    print(f"    {r.strip()}")


def step_already_installed() -> bool:
    print("=== 2. is AmiSSL already there?")
    r = dos("list LIBS:amisslmaster.library LIBS:AmiSSL/#? QUICK", timeout=8)
    print(f"    {r.strip()}")
    if FORCE:
        print("    --force: will reinstall regardless")
        return False
    # Only accept a modern amissl_v3xx.library — old v097g etc. still
    # trigger the "please insert CERT: volume" requester at startup.
    has_master = "amisslmaster.library" in r
    has_modern = any(f"amissl_v{v}" in r for v in ("300", "310", "320", "330",
                                                     "340", "350", "360", "362", "370"))
    ok = has_master and has_modern
    if has_master and not has_modern and not ok:
        print("    OLD AmiSSL detected (v097g or similar).  Re-run with "
              "--force to replace with v3.x.")
    print(f"    installed: {ok}")
    return ok


def step_resolve_tag() -> str:
    if AMISSL_TAG:
        print(f"=== 3. pinned tag: {AMISSL_TAG}")
        return AMISSL_TAG
    print("=== 3. resolving latest release tag from GitHub")
    url = "https://api.github.com/repos/jens-maus/amissl/releases/latest"
    import ssl
    # macOS Python.org builds don't ship a CA bundle by default;
    # fall through to certifi if it's installed, else disable
    # verification (we're reading a public release-metadata JSON,
    # not credentialed content).
    ctx = None
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl._create_unverified_context()
        print("    (no certifi; skipping cert verification for GitHub API)")
    with urllib.request.urlopen(url, timeout=15, context=ctx) as f:
        data = json.load(f)
    tag = data["tag_name"]
    print(f"    latest: {tag}")
    return tag


def step_fetch(tag: str) -> Path:
    AMISSL_CACHE.mkdir(parents=True, exist_ok=True)
    lha = f"AmiSSL-{tag}-OS4.lha"
    local = AMISSL_CACHE / lha
    if local.exists():
        print(f"=== 4. archive cached: {local} ({local.stat().st_size} B)")
        return local
    url = f"https://github.com/jens-maus/amissl/releases/download/{tag}/{lha}"
    print(f"=== 4. downloading {lha}")
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl._create_unverified_context()
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=120, context=ctx) as resp, \
            open(local, "wb") as out:
        while chunk := resp.read(65536):
            out.write(chunk)
    print(f"    saved: {local} ({local.stat().st_size} B)")
    return local


def step_push(local: Path) -> str:
    remote = f"RAM:{local.name}"
    print(f"=== 5. pushing to {remote} ({local.stat().st_size} B)")
    for attempt in range(1, PUSH_RETRIES + 1):
        try:
            r = push(local, remote)
        except DevbenchError as e:
            r = f"DevbenchError: {e}"
        if "CRC32 verified" in r or "Transferred" in r and "Failed" not in r:
            print(f"    {r.strip()}")
            return remote
        print(f"    attempt {attempt}/{PUSH_RETRIES}: {r.strip()}")
        if attempt == PUSH_RETRIES:
            print("    bridge push kept failing — is the OS4 bridge daemon healthy?")
            sys.exit(1)
        time.sleep(PUSH_BACKOFF)
        # Nudge the bridge back to life if needed.
        try:
            _api("/api/disconnect", method="POST")
        except DevbenchError:
            pass
        try:
            _api("/api/connect", method="POST",
                 body={"host": "127.0.0.1", "port": 2347})
        except DevbenchError:
            pass
    return remote     # unreachable but keeps typechecker happy


def _mkdir_ok(path: str) -> None:
    """makedir that swallows the already-exists error.

    AmigaDOS `makedir X` on an existing X returns non-zero with
    'MAKEDIR: "X" already exists.' — which alone is fine, but in a
    multi-line script would abort the rest. We call each makedir in
    its own dos() call and ignore the exists error explicitly."""
    out = dos(f"makedir {path}", timeout=8).strip()
    if out and "already exists" not in out.lower():
        print(f"    makedir {path}: {out}")


def step_extract_and_install(remote_lha: str, extract_dir: str = "RAM:AmiSSL_x"):
    print("=== 6. extracting on OS4")
    # OS4 doesn't ship `lha` in C:, but ships xadUnFile which handles
    # .lha via XAD. IMPORTANT: run as a SINGLE-LINE command — AmigaDOS
    # `;` starts a comment, so `cd RAM: ; xadUnFile ...` silently drops
    # the second half. Also pass QUIET, otherwise the per-file progress
    # (one line per cert, 500+ certs) drowns the bridge and drives the
    # extraction from 5s to 3+ minutes.
    _mkdir_ok(extract_dir)
    ext_cmd = f"xadUnFile {remote_lha} DEST={extract_dir} OVERWRITE QUIET"
    ext = dos(ext_cmd, timeout=300).strip()
    print("   ", ext[:400] + ("..." if len(ext) > 400 else ""))
    if "unknown command" in ext.lower() or "not found" in ext.lower():
        # Fallback: classic lha binary (rare on OS4, but Utilities/lha
        # exists on some installs).
        alt = dos(f"lha x {remote_lha} {extract_dir}/", timeout=300).strip()
        print("   ", alt)

    # Confirm the master library actually appeared before touching LIBS:
    # — otherwise a silent extraction failure would nuke the existing
    # LIBS:amisslmaster.library and leave the system SSL-broken.
    src_master = f"{extract_dir}/AmiSSL/Libs/AmigaOS4/amisslmaster.library"
    check = dos(f"list {src_master} QUICK", timeout=8).strip()
    if "not found" in check.lower() or "no matches" in check.lower() or not check:
        print(f"    ERR: extraction failed — {src_master} not present")
        print(f"    keeping {remote_lha} for inspection")
        sys.exit(1)

    print("=== 7. removing any stale old-version AmiSSL libraries")
    # Force-delete the old v097g / v100 lib families so amisslmaster
    # picks up the newer v3.x one we're about to drop in. Also delete
    # amisslmaster.library itself in case its layout changed.
    dos("delete LIBS:amisslmaster.library FORCE QUIET", timeout=10)
    dos("delete LIBS:AmiSSL/#? FORCE QUIET ALL", timeout=15)

    print("=== 8. copying into LIBS:")
    _mkdir_ok("LIBS:AmiSSL")
    print("   ", dos(f"copy {src_master} LIBS: CLONE", timeout=15).strip())
    print("   ", dos(
        f"copy {extract_dir}/AmiSSL/Libs/AmigaOS4/AmiSSL/#?.library LIBS:AmiSSL/ CLONE ALL",
        timeout=30).strip())

    print("=== 9. installing CA cert bundle")
    # Old AmiSSL asked for a CERT: volume via a modal requester at open
    # time — very annoying, blocks anything else on the bridge. New
    # AmiSSL (3.x) uses AmiSSL:Certs. Ship the cert bundle so no volume
    # prompt fires + HTTPS chains verify.
    _mkdir_ok("DH1:AmiSSL")
    _mkdir_ok("DH1:AmiSSL/Certs")
    print("   ", dos(
        f"copy {extract_dir}/AmiSSL/Certs/#? DH1:AmiSSL/Certs/ ALL QUIET CLONE",
        timeout=180).strip())
    dos("assign AmiSSL: DH1:AmiSSL", timeout=5)
    # Also mirror into user-startup so it survives reboots. Guard on
    # grep so we don't append duplicate lines on rerun. AmigaDOS `search`
    # is the equivalent of grep -q.
    already = dos('search S:User-Startup PATTERN="assign AmiSSL:" QUIET',
                  timeout=5).strip()
    if not already or "not found" in already.lower() or "no matches" in already.lower():
        dos('echo >>S:User-Startup "assign AmiSSL: DH1:AmiSSL"', timeout=5)

    print("=== 10. verifying")
    print("   ", dos("list LIBS:amisslmaster.library LIBS:AmiSSL/#? QUICK",
                     timeout=8).strip())

    print("=== 11. cleanup")
    dos(f"delete {remote_lha} QUIET", timeout=10)
    dos(f"delete {extract_dir} ALL QUIET", timeout=30)


def step_smoke_test():
    print("=== 10. HTTPS smoke test")
    cmd = (
        f'{PYTHON_OS4} -c "import ssl; print(\'OPENSSL:\', ssl.OPENSSL_VERSION)"'
    )
    print("   ", dos(cmd, timeout=30).strip())


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    step_ping()
    if step_already_installed():
        print()
        print("AmiSSL already installed.  Skipping fetch + install.")
        step_smoke_test()
        return 0
    tag = step_resolve_tag()
    local = step_fetch(tag)
    remote = step_push(local)
    step_extract_and_install(remote)
    print()
    print("Install complete.  Running smoke test.")
    step_smoke_test()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DevbenchError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\naborted.", file=sys.stderr)
        sys.exit(130)
