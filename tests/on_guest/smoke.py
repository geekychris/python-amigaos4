"""On-guest smoke test — mandatory pre-PR sweep.

Runs a fixed sequence of Python capability probes on the guest.
Each writes PASS: <name> or FAIL: <name>: <reason> to T:smoke.log.

Coverage is split into three tiers:

  Tier 1 — CORE (must pass, else the interpreter is unusable):
    version, sys_path, stdlib_import, encodings, print_stdout,
    write_file_via_open, write_file_via_os_open, read_own_write,
    listdir, stat

  Tier 2 — EMBED-CRITICAL (for GemRB or any C host that
    embeds libpython.a; failures block integration):
    threading_basic, gc_run, pyimport_math, exception_raise,
    unicode_roundtrip

  Tier 3 — INTEGRATION (nice-to-have, exercises third-party
    surfaces that pip users hit):
    import_amiga_pip, resolver_smoke, cache_smoke, https_import,
    ssl_import, socket_import

If Tier 1 fails, don't ship. If Tier 2 fails, don't merge to
main. Tier 3 failures are release-notes-worthy but non-blocking.

Deploy:  xdftool amigaos4-dev.hdf write tests/on_guest/smoke.py smoke.py
Run:     setenv PYTHONHOME DH1:
         setenv PYTHONPATH "DH1:lib"
         DH1:python-os4 DH1:smoke.py
Read:    curl -s "http://localhost:3000/api/file?path=T:smoke.log&..."
"""
from __future__ import annotations
import os
import sys
import traceback

LOG = "T:smoke.log"
_results: list[tuple[str, bool, str, str]] = []   # (name, ok, tier, detail)


def _record(name, ok, tier, detail=""):
    _results.append((name, ok, tier, detail))
    line = ("PASS" if ok else "FAIL") + f": [{tier}] {name}"
    if detail:
        line += f" — {detail}"
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _check(name, tier, fn):
    try:
        detail = fn() or ""
    except BaseException as e:
        tb = traceback.format_exc()
        _record(name, False, tier, f"{type(e).__name__}: {e}\n{tb}")
        return
    _record(name, True, tier, detail if isinstance(detail, str) else "")


with open(LOG, "w") as f:
    f.write(f"=== smoke test @ {sys.version.split()[0]} ===\n\n")


# ─── TIER 1: CORE ─────────────────────────────────────────────────────
def _version():
    return sys.version.split()[0]
_check("version", "CORE", _version)


def _syspath():
    if not sys.path:
        raise RuntimeError("sys.path empty")
    if not any("lib" in p for p in sys.path):
        raise RuntimeError(f"'lib' missing from sys.path: {sys.path}")
    return str(sys.path)
_check("sys_path", "CORE", _syspath)


def _stdlib():
    import json, os, io, re, collections, itertools, functools  # noqa
    return "json os io re collections itertools functools"
_check("stdlib_import", "CORE", _stdlib)


def _encodings():
    # If encodings didn't init, sys.stdout wouldn't work — but check
    # the module is importable and utf-8 codec is registered.
    import encodings.utf_8  # noqa
    "hello".encode("utf-8")
    b"hello".decode("utf-8")
    return "utf-8 roundtrip ok"
_check("encodings", "CORE", _encodings)


def _print():
    print("smoke_stdout_marker")
    return "printed marker to stdout"
_check("print_stdout", "CORE", _print)


def _write_file():
    path = "T:smoke_write.txt"
    payload = "smoke_write_payload"
    try: os.remove(path)
    except OSError: pass
    with open(path, "w") as f:
        f.write(payload)
    with open(path, "r") as f:
        got = f.read()
    if got != payload:
        raise RuntimeError(f"read-back mismatch: {got!r} vs {payload!r}")
    try: os.remove(path)
    except OSError: pass
    return f"wrote+read {len(payload)}B via open()"
_check("write_file_via_open", "CORE", _write_file)


def _os_open():
    path = "T:smoke_osopen.txt"
    payload = b"smoke_osopen_payload"
    try: os.remove(path)
    except OSError: pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    n = os.write(fd, payload)
    os.close(fd)
    if n != len(payload):
        raise RuntimeError(f"os.write returned {n}, want {len(payload)}")
    fd = os.open(path, os.O_RDONLY)
    got = os.read(fd, 1024)
    os.close(fd)
    if got != payload:
        raise RuntimeError(f"os.read got {got!r} want {payload!r}")
    try: os.remove(path)
    except OSError: pass
    return f"os.open+write+read {len(payload)}B roundtrip"
_check("write_file_via_os_open", "CORE", _os_open)


def _read_own_write():
    """The specific gap that hid the merge regression — verifies the
    file that was 'created' is actually visible via the AmigaDOS
    filesystem, not just to newlib's virtual view."""
    path = "T:smoke_visibility.txt"
    with open(path, "w") as f:
        f.write("check_me")
    # Existence probe via os.stat (not fstat — path-based)
    st = os.stat(path)
    if st.st_size != len("check_me"):
        raise RuntimeError(f"stat size {st.st_size} != 8")
    # Also probe via os.listdir on T:
    listing = os.listdir("T:")
    if "smoke_visibility.txt" not in listing:
        raise RuntimeError("file not in os.listdir('T:') — "
                           "written to virtual location, not real disk!")
    try: os.remove(path)
    except OSError: pass
    return "file visible to both os.stat and os.listdir"
_check("read_own_write", "CORE", _read_own_write)


def _listdir():
    entries = os.listdir("DH1:")
    if "python-os4" not in entries:
        raise RuntimeError(f"python-os4 not in DH1: entries; got: {entries[:10]}")
    return f"DH1: has {len(entries)} entries incl. python-os4"
_check("listdir", "CORE", _listdir)


def _stat():
    st = os.stat("DH1:python-os4")
    if st.st_size < 1_000_000:
        raise RuntimeError(f"python-os4 too small: {st.st_size}B")
    return f"python-os4 stat.st_size = {st.st_size}"
_check("stat", "CORE", _stat)


# ─── TIER 2: EMBED-CRITICAL (matters for GemRB / any libpython.a host) ─
def _threading():
    import threading
    hit = []
    ev = threading.Event()
    def worker():
        hit.append("worker")
        ev.set()
    t = threading.Thread(target=worker)
    t.start()
    if not ev.wait(timeout=5):
        raise RuntimeError("worker thread never signalled")
    t.join(timeout=5)
    if hit != ["worker"]:
        raise RuntimeError(f"unexpected hit list: {hit}")
    return "spawned thread + event signal ok"
_check("threading_basic", "EMBED", _threading)


def _gc():
    import gc
    gc.collect()
    stats = gc.get_stats()
    if not stats:
        raise RuntimeError("gc.get_stats() returned empty")
    return f"gc.collect ok; {len(stats)} generation stats"
_check("gc_run", "EMBED", _gc)


def _pyimport_math():
    """Import a C-extension module — proves the extension-loading
    machinery in the embedded interpreter works."""
    import math
    if abs(math.sqrt(2.0) - 1.4142135) > 1e-6:
        raise RuntimeError("math.sqrt broken")
    return "math.sqrt(2) ok"
_check("pyimport_math", "EMBED", _pyimport_math)


def _exception():
    try:
        raise ValueError("hello_exception")
    except ValueError as e:
        if "hello_exception" not in str(e):
            raise RuntimeError(f"exception message wrong: {e}")
    return "raise/catch/message ok"
_check("exception_raise", "EMBED", _exception)


def _unicode():
    s = "hello 世界 \U0001f600"   # 世界 + emoji
    b = s.encode("utf-8")
    s2 = b.decode("utf-8")
    if s != s2:
        raise RuntimeError(f"unicode roundtrip lost: {s!r} vs {s2!r}")
    return f"{len(s)} chars, {len(b)} bytes, utf-8 lossless"
_check("unicode_roundtrip", "EMBED", _unicode)


# ─── TIER 3: INTEGRATION (pip / SSL / socket) ─────────────────────────
def _import_amiga_pip():
    import amiga.pip as p
    if not hasattr(p, "install"):
        raise RuntimeError("amiga.pip has no install()")
    if not hasattr(p, "DEFAULT_INDEX_URL"):
        raise RuntimeError("amiga.pip has no DEFAULT_INDEX_URL")
    return "amiga.pip has install() + DEFAULT_INDEX_URL"
_check("import_amiga_pip", "INTEGRATION", _import_amiga_pip)


def _resolver():
    from amiga.pip import resolver
    data = {"info": {"name": "x", "version": "1.0.0"},
            "releases": {"1.0.0": [
                {"filename": "x-1.0.0-py3-none-any.whl",
                 "url": "https://ex/x.whl",
                 "digests": {"sha256": "0" * 64}}]}}
    r = resolver.resolve_from_json(data)
    if r.version != "1.0.0":
        raise RuntimeError(f"resolver picked {r.version}")
    return f"resolver returned {r.name} {r.version}"
_check("resolver_smoke", "INTEGRATION", _resolver)


def _cache():
    """Cache module loads + SHA-256 works (would have caught the
    hashlib-init-hangs regression from pre-merge sessions)."""
    from amiga.pip import cache
    p = "T:smoke_cache.bin"
    with open(p, "wb") as f:
        f.write(b"cache-check")
    h = cache.sha256_file(p)
    try: os.remove(p)
    except OSError: pass
    # Known value for "cache-check"
    import hashlib
    expected = hashlib.sha256(b"cache-check").hexdigest()
    if h != expected:
        raise RuntimeError(f"sha256 mismatch: {h} vs {expected}")
    return f"cache.sha256_file matches hashlib"
_check("cache_smoke", "INTEGRATION", _cache)


def _https_import():
    from amiga import https
    if not hasattr(https, "get"):
        raise RuntimeError("amiga.https has no get()")
    return "amiga.https.get present"
_check("https_import", "INTEGRATION", _https_import)


def _ssl_import():
    import ssl
    ctx = ssl.create_default_context()
    if not ctx:
        raise RuntimeError("ssl.create_default_context returned None")
    return "ssl module loaded, default_context created"
_check("ssl_import", "INTEGRATION", _ssl_import)


def _socket_import():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.close()
    return "socket AF_INET SOCK_STREAM created + closed"
_check("socket_import", "INTEGRATION", _socket_import)


# ─── summary ──────────────────────────────────────────────────────────
tiers: dict[str, dict[str, int]] = {}
for name, ok, tier, _ in _results:
    d = tiers.setdefault(tier, {"pass": 0, "fail": 0})
    d["pass" if ok else "fail"] += 1

with open(LOG, "a") as f:
    f.write(f"\n=== SUMMARY ===\n")
    for tier in ("CORE", "EMBED", "INTEGRATION"):
        d = tiers.get(tier, {"pass": 0, "fail": 0})
        total = d["pass"] + d["fail"]
        marker = "OK" if d["fail"] == 0 else f"{d['fail']} FAIL"
        f.write(f"  {tier:12s}: {d['pass']}/{total} pass  [{marker}]\n")
    failed = [n for n, ok, _, _ in _results if not ok]
    if failed:
        f.write(f"\nFailed checks:\n")
        for name in failed:
            f.write(f"  - {name}\n")

# Exit status: 0 if all pass, 1 if any CORE fail, 2 if EMBED fail,
# 3 if only INTEGRATION fails. Lets CI gate by severity.
if any(not ok and tier == "CORE" for _, ok, tier, _ in _results):
    print(f"smoke: CORE FAILURE — do not ship")
    sys.exit(1)
if any(not ok and tier == "EMBED" for _, ok, tier, _ in _results):
    print(f"smoke: EMBED failure — libpython.a integration broken")
    sys.exit(2)
if any(not ok for _, ok, _, _ in _results):
    print(f"smoke: INTEGRATION failure — pip/ssl/socket surface degraded")
    sys.exit(3)

n_pass = sum(1 for _, ok, _, _ in _results if ok)
print(f"smoke: {n_pass}/{len(_results)} passed — all tiers green")
sys.exit(0)
