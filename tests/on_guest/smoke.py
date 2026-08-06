"""On-guest smoke test — the minimum you should run after every
deploy, guaranteed to catch the regressions we've hit before.

Runs a fixed sequence of Python capability probes. Each writes
PASS: <name> or FAIL: <name>: <reason> to T:smoke.log. Anything
failing means the interpreter is broken for that capability.

The one this WOULD have caught in the merge session:
    5. write_file_via_open
       user-code open('T:x','w').write() silently discarded
       (my week of debugging, saved).

Deploy:  xdftool amigaos4-dev.hdf write tests/on_guest/smoke.py smoke.py
Run:     setenv PYTHONHOME DH1: & setenv PYTHONPATH "DH1:lib"
         DH1:python-os4 DH1:smoke.py
Read:    curl -s "http://localhost:3000/api/file?path=T:smoke.log&..."

Exit code is 0 if all PASS, non-zero otherwise. Read T:smoke.log
for per-check detail even in the PASS case (records what ran).
"""
from __future__ import annotations
import os
import sys
import traceback

LOG = "T:smoke.log"
_results = []


def _record(name, ok, detail=""):
    _results.append((name, ok, detail))
    line = ("PASS" if ok else "FAIL") + f": {name}"
    if detail:
        line += f" — {detail}"
    with open(LOG, "a") as f:
        f.write(line + "\n")


def _check(name, fn):
    try:
        detail = fn() or ""
    except BaseException as e:
        tb = traceback.format_exc()
        _record(name, False, f"{type(e).__name__}: {e}\n{tb}")
        return
    _record(name, True, detail if isinstance(detail, str) else "")


# Clear/create the log
with open(LOG, "w") as f:
    f.write(f"=== smoke test @ {sys.version.split()[0]} ===\n")


# 1. interpreter version + platform
def _version():
    return sys.version.split()[0]
_check("version", _version)


# 2. sys.path is populated (no encodings.py silent-init failure)
def _syspath():
    if not sys.path:
        raise RuntimeError("sys.path is empty!")
    if not any("lib" in p for p in sys.path):
        raise RuntimeError(f"'lib' not in any sys.path entry: {sys.path}")
    return str(sys.path)
_check("sys_path", _syspath)


# 3. import stdlib basics
def _stdlib():
    import json, os, io, re, collections, itertools, functools  # noqa
    return "json os io re collections itertools functools"
_check("stdlib_import", _stdlib)


# 4. print to stdout (via > redirect from the shell)
def _print():
    print("smoke_stdout_marker")
    return "printed marker to stdout"
_check("print_stdout", _print)


# 5. WRITE a file from user code (THE regression that hit us)
def _write_file():
    path = "T:smoke_write.txt"
    payload = "smoke_write_payload"
    try:
        os.remove(path)
    except OSError:
        pass
    with open(path, "w") as f:
        f.write(payload)
    # Read back — verifies both write AND read work
    with open(path, "r") as f:
        got = f.read()
    if got != payload:
        raise RuntimeError(f"read back wrong content: {got!r} vs {payload!r}")
    try:
        os.remove(path)
    except OSError:
        pass
    return f"wrote+read {len(payload)}B via open()"
_check("write_file_via_open", _write_file)


# 6. Same, but via low-level os.open (different code path in newlib)
def _os_open():
    path = "T:smoke_osopen.txt"
    payload = b"smoke_osopen_payload"
    try:
        os.remove(path)
    except OSError:
        pass
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    n = os.write(fd, payload)
    os.close(fd)
    if n != len(payload):
        raise RuntimeError(f"os.write wrote {n} not {len(payload)}")
    fd = os.open(path, os.O_RDONLY)
    got = os.read(fd, 1024)
    os.close(fd)
    if got != payload:
        raise RuntimeError(f"os.read got {got!r} not {payload!r}")
    try:
        os.remove(path)
    except OSError:
        pass
    return f"os.open + os.write + os.read {len(payload)}B ok"
_check("write_file_via_os_open", _os_open)


# 7. import amiga.pip (validates the bindings tree + package loads)
def _import_amiga_pip():
    import amiga.pip as p
    if not hasattr(p, "install"):
        raise RuntimeError("amiga.pip has no `install` — old version deployed?")
    return f"amiga.pip.install present"
_check("import_amiga_pip", _import_amiga_pip)


# 8. amiga.pip resolver against canned JSON (no network needed)
def _resolver_smoke():
    from amiga.pip import resolver
    data = {"info": {"name": "x", "version": "1.0.0"},
            "releases": {"1.0.0": [
                {"filename": "x-1.0.0-py3-none-any.whl",
                 "url": "https://ex/x.whl",
                 "digests": {"sha256": "0" * 64}}
            ]}}
    r = resolver.resolve_from_json(data)
    if r.version != "1.0.0":
        raise RuntimeError(f"resolver picked {r.version}")
    return "resolver.resolve_from_json returns InstalledPackage"
_check("resolver_smoke", _resolver_smoke)


# 9. list a directory (opendir + readdir path)
def _listdir():
    entries = os.listdir("DH1:")
    if "python-os4" not in entries:
        raise RuntimeError(
            f"expected python-os4 in DH1: entries; got first 10: {entries[:10]}")
    return f"{len(entries)} entries in DH1:, python-os4 present"
_check("listdir", _listdir)


# 10. stat a file (stat shim path)
def _stat():
    st = os.stat("DH1:python-os4")
    if st.st_size < 1_000_000:
        raise RuntimeError(f"python-os4 stat size too small: {st.st_size}")
    return f"python-os4 stat.st_size = {st.st_size}"
_check("stat", _stat)


# ---- summary ----
n_pass = sum(1 for _, ok, _ in _results if ok)
n_fail = len(_results) - n_pass
with open(LOG, "a") as f:
    f.write(f"\n=== smoke summary: {n_pass}/{len(_results)} PASS ===\n")
    if n_fail:
        f.write("Failed:\n")
        for name, ok, _ in _results:
            if not ok:
                f.write(f"  - {name}\n")

print(f"smoke: {n_pass}/{len(_results)} passed")
sys.exit(0 if n_fail == 0 else 1)
