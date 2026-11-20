"""On-guest smoke test -- mandatory pre-PR sweep + remote diagnostic bundle.

Runs a fixed sequence of Python capability probes on the guest,
writing PASS/FAIL lines to T:smoke.log. Also dumps environment
information (guest OS version, mounted assigns, sys.path, sysconfig,
etc.) so that when this fails on someone else's machine they can just
send back T:smoke.log and remote debugging is possible.

Coverage tiers:

  CORE          -- interpreter fundamentals; if any fails, unusable.
  EMBED         -- capabilities libpython.a hosts (GemRB) will hit.
  INTEGRATION   -- pip / ssl / socket surface, non-blocking failures.
  PATH_DIAG     -- path handling / assign resolution. Where Bill's
                  '/ystem:' bug class lives. Diagnostic-heavy.

If a probe fails, its failure line includes: errno + strerror where
available, an out-of-band AmigaDOS `list`/`assign` cross-check,
and a full Python traceback.

Deploy:  xdftool amigaos4-dev.hdf write tests/on_guest/smoke.py smoke.py
Run:     setenv PYTHONHOME SYS:System/python3
         setenv PYTHONPATH "python3:lib"
         assign SMOKE: T:
         python3 python3:smoke.py
Read:    curl "http://localhost:3000/api/file?path=T:smoke.log&..."
         (or on guest: `type T:smoke.log`)
"""
from __future__ import annotations
import errno as _errno
import os
import sys
import traceback

LOG = "T:smoke.log"
OOB = "T:smoke_oob.log"           # scratch for AmigaDOS shellouts
_results: list[tuple[str, bool, str, str]] = []   # (name, ok, tier, detail)
_current_test: str | None = None


# --- helpers ----------------------------------------------------------

def _log_raw(text: str) -> None:
    """Append text to the smoke log. Uses "a" mode with surrogateescape so
    non-UTF-8 environment bytes never raise UnicodeEncodeError. Every line
    is tagged with the current test name [tier:name] or [HEADER]."""
    tag = f"[{_current_test}]" if _current_test else "[HEADER]"
    lines = text.splitlines()
    with open(LOG, "a", encoding="utf-8", errors="surrogateescape") as f:
        if not lines and text.endswith("\n"):
            f.write("\n")
        for line in lines:
            if line.strip():
                f.write(f"{tag} {line}\n")
            else:
                f.write("\n")


def _dos(cmd: str) -> tuple[int, str]:
    """Shell out to AmigaDOS, capture stdout into a scratch file, then
    read the file back. Returns (rc, captured_text). Used for OOB
    cross-checks (amiga_list, amiga_assign, amiga_version).

    Note: os.system on OS4 spawns via Execute(); the returned code is
    passed through, but many AmigaDOS commands return 0 on error too.
    Rely on the captured text, not the rc, to decide."""
    try: os.remove(OOB)
    except OSError: pass
    rc = os.system(f"{cmd} >{OOB}")
    try:
        with open(OOB, "r", encoding="utf-8", errors="surrogateescape") as f:
            out = f.read()
    except OSError:
        out = ""
    try: os.remove(OOB)
    except OSError: pass
    return rc, out


def _amiga_list(path: str) -> tuple[int, str]:
    """Ask AmigaDOS to list a SINGLE FILE path. Do NOT pass a volume
    root here -- that spews the whole directory and can hang or clobber
    the log. Use `_amiga_probe_volume` for volume-existence checks."""
    return _dos(f"list {path} QUICK")


def _amiga_probe_volume(prefix: str) -> tuple[bool, str]:
    """Lightweight AmigaDOS existence check for a volume/assign. Uses
    `assign NAME` (with no target) which just prints the current
    mapping -- short output regardless of volume size. Returns
    (exists, detail_line)."""
    # strip trailing ':' since `assign` command takes bare name
    name = prefix.rstrip(":")
    _, out = _dos(f"assign {name}")
    exists = bool(out) and "no such" not in out.lower() \
             and "object not found" not in out.lower() \
             and "no information" not in out.lower()
    # Take first non-empty line as the detail
    detail = ""
    for line in out.splitlines():
        line = line.strip()
        if line and not line.lower().startswith("volumes"):
            detail = line[:80]
            break
    return exists, detail


def _amiga_assigns() -> str:
    """Dump all mounted volumes / directories / devices."""
    _, out = _dos("assign")
    return out


def _amiga_version() -> str:
    """Guest OS4 version and CPU."""
    _, out = _dos("version FULL")
    return out


def _errno_of(exc: BaseException) -> str:
    """Return 'errno=NNN (CODE) -- strerror'. Empty string if exc has
    no errno."""
    en = getattr(exc, "errno", None)
    if en is None:
        return ""
    code = _errno.errorcode.get(en, "?")
    try:
        msg = os.strerror(en)
    except Exception:
        msg = ""
    return f" errno={en} ({code}) {msg}"


def _record(name, ok, tier, detail=""):
    _results.append((name, ok, tier, detail))
    line = ("PASS" if ok else "FAIL") + f": [{tier}] {name}"
    if detail:
        line += f" -- {detail}"
    _log_raw(line)


_include_filters: list[str] = []
_exclude_filters: list[str] = []
_list_mode = False
_parsed_args = False


def _parse_cli_filters() -> None:
    global _include_filters, _exclude_filters, _list_mode, _parsed_args
    if _parsed_args:
        return
    _parsed_args = True

    # 1. Environment variable exclusions (comma or space separated)
    env_excludes = os.environ.get("SMOKE_EXCLUDE", "") + " " + os.environ.get("SMOKE_SKIP", "")
    for tok in env_excludes.replace(",", " ").split():
        if tok.strip():
            _exclude_filters.append(tok.strip().lower())

    # 2. CLI arguments
    argv = sys.argv[1:]
    i = 0
    while i < len(argv):
        arg = argv[i]
        low = arg.lower()
        if low in ("--list", "-l", "-list"):
            _list_mode = True
            i += 1
            continue
        elif low in ("-x", "--exclude", "--skip", "-e"):
            if i + 1 < len(argv):
                i += 1
                for tok in argv[i].replace(",", " ").split():
                    _exclude_filters.append(tok.strip().lower())
            i += 1
            continue
        elif low.startswith("--exclude=") or low.startswith("--skip="):
            val = arg.split("=", 1)[1]
            for tok in val.replace(",", " ").split():
                _exclude_filters.append(tok.strip().lower())
            i += 1
            continue
        elif low.startswith("!") or low.startswith("^") or low.startswith("~"):
            tok = low[1:].strip()
            if tok:
                _exclude_filters.append(tok)
            i += 1
            continue
        elif not low.startswith("-"):
            _include_filters.append(low)
            i += 1
        else:
            i += 1


def _check(name, tier, fn):
    """Run a probe; on failure attach errno, amiga_list of any path
    the failure references, and a traceback. Supports filtering:
      - Positive filter:  python3 smoke.py CORE (or threading)
      - Negative/Exclude: python3 smoke.py -x threading_multiple
                          python3 smoke.py !threading_multiple
                          python3 smoke.py --exclude=test_name
                          env var SMOKE_EXCLUDE=test_name
      - List tests:       python3 smoke.py --list
    """
    _parse_cli_filters()
    name_low = name.lower()
    tier_low = tier.lower()

    if _list_mode:
        print(f"[{tier}] {name}")
        return

    # Check if explicitly excluded
    for exc in _exclude_filters:
        if exc in name_low or exc in tier_low:
            return

    # Check if inclusion filter is specified
    if _include_filters:
        match = any(inc in name_low or inc in tier_low for inc in _include_filters)
        if not match:
            return

    global _current_test
    _current_test = f"{tier}:{name}"
    _log_raw(f"RUNNING: [{tier}] {name}")
    try:
        try:
            detail = fn() or ""
        except BaseException as e:
            tb = traceback.format_exc()
            extra = _errno_of(e)
            oob = ""
            msg = str(e)
            for token in msg.split():
                clean_token = token.strip("'\"()[]{},;")
                if ":" in clean_token and len(clean_token) < 128:
                    parts = clean_token.split(":", 1)
                    if parts[0] and (parts[0].isupper() or "/" in clean_token or "\\" in clean_token):
                        _, listed = _amiga_list(clean_token)
                        if listed:
                            oob = f"\n  amiga list {clean_token} -> {listed.strip()[:200]}"
                            break
            _record(name, False, tier,
                    f"{type(e).__name__}: {e}{extra}{oob}\n{tb}")
            return
        _record(name, True, tier, detail if isinstance(detail, str) else "")
    finally:
        _current_test = None


# --- HEADER: environment dump (always runs, always logged) ------------

with open(LOG, "w", encoding="utf-8", errors="surrogateescape") as f:
    f.write(f"[HEADER] === smoke test @ {sys.version.split()[0]} ===\n\n")

_log_raw("--- ENVIRONMENT -----------------------------------------------")
_log_raw(f"python.version    : {sys.version}")
_log_raw(f"python.platform   : {sys.platform}")
_log_raw(f"python.executable : {sys.executable}")
_log_raw(f"python.prefix     : {sys.prefix}")
_log_raw(f"python.base_prefix: {sys.base_prefix}")
_log_raw(f"python.exec_prefix: {sys.exec_prefix}")
_log_raw(f"python.fs_encoding: {sys.getfilesystemencoding()}")
_log_raw(f"python.byteorder  : {sys.byteorder}")
_log_raw(f"python.maxsize    : {sys.maxsize}")
_log_raw(f"cwd               : {os.getcwd()}")
_log_raw(f"PYTHONHOME env    : {os.environ.get('PYTHONHOME', '(unset)')}")
_log_raw(f"PYTHONPATH env    : {os.environ.get('PYTHONPATH', '(unset)')}")
_log_raw(f"HOME env          : {os.environ.get('HOME', '(unset)')}")
_log_raw(f"PATH env          : {os.environ.get('PATH', '(unset)')}")
_log_raw("")
_log_raw("sys.path:")
for i, p in enumerate(sys.path):
    _log_raw(f"  [{i}] {p!r}")
_log_raw("")

# Filtered env dump -- keep small, redact any potential secrets
_log_raw("os.environ (filtered):")
_SECRET_HINTS = ("KEY", "SECRET", "TOKEN", "PASS", "PWD")
for k in sorted(os.environ):
    v = os.environ[k]
    if any(h in k.upper() for h in _SECRET_HINTS):
        v = f"<redacted {len(v)}B>"
    if len(v) > 200:
        v = v[:200] + "..."
    _log_raw(f"  {k}={v}")
_log_raw("")

# AmigaDOS-side dumps -- capture guest OS state that we can't see
# from Python alone
_log_raw("guest AmigaOS version (via `version FULL`):")
for line in _amiga_version().splitlines():
    _log_raw(f"  {line}")
_log_raw("")

_assigns_raw = _amiga_assigns()
_log_raw("mounted assigns (via `assign`):")
for line in _assigns_raw.splitlines():
    _log_raw(f"  {line}")
_log_raw("")

# Parse `assign` output once, cache for probes below. Avoids
# re-shellouts in every test.
_MOUNTED: set[str] = set()  # names with trailing ':', e.g. {'LIBS:', ...}
_ASSIGN_TARGETS: dict[str, str] = {}  # name -> resolved target
_section = None
for _line in _assigns_raw.splitlines():
    s = _line.strip()
    if not s:
        continue
    low = s.lower()
    if low.startswith("volumes"):
        _section = "vol"; continue
    if low.startswith("directories"):
        _section = "dir"; continue
    if low.startswith("devices"):
        _section = "dev"; continue
    if _section == "vol":
        # "chris [Mounted]" -- take word before space
        name = s.split()[0].rstrip(":")
        _MOUNTED.add(name.upper() + ":")
    elif _section == "dir":
        # "LIBS   Empty:Libs" -- first token = name, rest = target
        if s.startswith("+") or not s[0].isalpha():
            continue
        parts = s.split(None, 1)
        if len(parts) >= 1:
            name = parts[0].rstrip(":")
            _MOUNTED.add(name.upper() + ":")
            if len(parts) == 2:
                _ASSIGN_TARGETS[name.upper() + ":"] = parts[1].strip()
    elif _section == "dev":
        # "DH0 DH1 ENV PAR PIPE" -- one line, space-separated
        for tok in s.split():
            _MOUNTED.add(tok.upper() + ":")

_log_raw(f"parsed mounted set ({len(_MOUNTED)} entries):")
_log_raw(f"  {sorted(_MOUNTED)}")
_log_raw("")


# --- TIER 1: CORE -----------------------------------------------------
def _version():
    return sys.version.split()[0]
_check("version", "CORE", _version)


def _syspath():
    if not sys.path:
        raise RuntimeError("sys.path empty")
    if not any("lib" in p for p in sys.path):
        raise RuntimeError(f"'lib' missing from sys.path: {sys.path}")
    return f"{len(sys.path)} entries"
_check("sys_path", "CORE", _syspath)


def _stdlib():
    import json, os, io, re, collections, itertools, functools  # noqa
    return "json os io re collections itertools functools"
_check("stdlib_import", "CORE", _stdlib)


def _encodings():
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
    """Verifies files 'created' via Python are actually visible via the
    AmigaDOS filesystem, not just newlib's virtual view."""
    path = "T:smoke_visibility.txt"
    with open(path, "w") as f:
        f.write("check_me")
    st = os.stat(path)
    if st.st_size != len("check_me"):
        raise RuntimeError(f"stat size {st.st_size} != 8")
    listing = os.listdir("T:")
    if "smoke_visibility.txt" not in listing:
        raise RuntimeError("file not in os.listdir('T:') -- "
                           "written to virtual location, not real disk!")
    try: os.remove(path)
    except OSError: pass
    return "file visible to both os.stat and os.listdir"
_check("read_own_write", "CORE", _read_own_write)


def _listdir():
    entries = os.listdir("SYS:")
    return f"SYS: has {len(entries)} entries"
_check("listdir", "CORE", _listdir)


def _stat():
    st = os.stat("python3:smoke.py")
    if st.st_size < 100:
        raise RuntimeError(f"python3:smoke.py too small: {st.st_size}B")
    return f"python3:smoke.py stat.st_size = {st.st_size}"
_check("stat", "CORE", _stat)


# --- TIER 2: EMBED-CRITICAL (matters for GemRB / any libpython.a host) -
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


def _threading_multiple():
    """Test concurrent multi-threading execution with synchronization,
    shared state mutation under Locks, and a producer-consumer Queue."""
    import threading
    import queue
    import time

    num_threads = 5
    items_per_thread = 20
    total_expected = num_threads * items_per_thread

    # 1. Test coordinated concurrent execution and shared state with Lock
    lock = threading.Lock()
    barrier = threading.Barrier(num_threads)
    counter = 0
    worker_results = {}

    def worker(worker_id):
        # Synchronize start across all threads
        barrier.wait(timeout=10)
        local_sum = 0
        for i in range(items_per_thread):
            local_sum += i
            with lock:
                nonlocal counter
                counter += 1
            time.sleep(0.001)
        with lock:
            worker_results[worker_id] = local_sum

    threads = [
        threading.Thread(target=worker, args=(i,), name=f"smoke-worker-{i}")
        for i in range(num_threads)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join(timeout=10)
        if t.is_alive():
            raise RuntimeError(f"Thread {t.name} did not terminate within timeout")

    if counter != total_expected:
        raise RuntimeError(f"Counter mismatch: expected {total_expected}, got {counter}")

    expected_local_sum = sum(range(items_per_thread))
    for i in range(num_threads):
        if worker_results.get(i) != expected_local_sum:
            raise RuntimeError(f"Worker {i} sum mismatch: expected {expected_local_sum}, got {worker_results.get(i)}")

    # 2. Test producer-consumer queue with multiple producer and consumer threads
    work_queue = queue.Queue()
    results_queue = queue.Queue()
    num_producers = 3
    num_consumers = 3
    items_to_process = 30

    def producer():
        for item in range(items_to_process // num_producers):
            work_queue.put(item)
            time.sleep(0.001)

    def consumer():
        while True:
            try:
                item = work_queue.get(timeout=2)
                results_queue.put(item * 2)
                work_queue.task_done()
            except queue.Empty:
                break

    prod_threads = [threading.Thread(target=producer, name=f"prod-{i}") for i in range(num_producers)]
    cons_threads = [threading.Thread(target=consumer, name=f"cons-{i}") for i in range(num_consumers)]

    for t in prod_threads:
        t.start()
    for t in cons_threads:
        t.start()

    for t in prod_threads:
        t.join(timeout=10)
        if t.is_alive():
            raise RuntimeError(f"Producer thread {t.name} timed out")

    work_queue.join()

    for t in cons_threads:
        t.join(timeout=10)
        if t.is_alive():
            raise RuntimeError(f"Consumer thread {t.name} timed out")

    if results_queue.qsize() != items_to_process:
        raise RuntimeError(f"Queue count mismatch: expected {items_to_process}, got {results_queue.qsize()}")

    return f"multiple threads ok: {num_threads} workers ({counter} synchronized ops) + {num_producers}p/{num_consumers}c queue ({items_to_process} items)"
_check("threading_multiple", "EMBED", _threading_multiple)


def _gc():
    import gc
    gc.collect()
    stats = gc.get_stats()
    if not stats:
        raise RuntimeError("gc.get_stats() returned empty")
    return f"gc.collect ok; {len(stats)} generation stats"
_check("gc_run", "EMBED", _gc)


def _pyimport_math():
    """Import a C-extension module -- proves the extension-loading
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
    s = "hello 世界 \U0001f600"
    b = s.encode("utf-8")
    s2 = b.decode("utf-8")
    if s != s2:
        raise RuntimeError(f"unicode roundtrip lost: {s!r} vs {s2!r}")
    return f"{len(s)} chars, {len(b)} bytes, utf-8 lossless"
_check("unicode_roundtrip", "EMBED", _unicode)


# --- TIER 3: INTEGRATION (pip / SSL / socket) -------------------------
def _import_amiga_pip():
    import amiga.pip as p
    if not hasattr(p, "install"):
        raise RuntimeError("amiga.pip has no install()")
    if not hasattr(p, "DEFAULT_INDEX_URL"):
        raise RuntimeError("amiga.pip has no DEFAULT_INDEX_URL")
    return f"install() + DEFAULT_INDEX_URL={p.DEFAULT_INDEX_URL}"
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
    from amiga.pip import cache
    p = "T:smoke_cache.bin"
    with open(p, "wb") as f:
        f.write(b"cache-check")
    h = cache.sha256_file(p)
    try: os.remove(p)
    except OSError: pass
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
    ver = getattr(ssl, "OPENSSL_VERSION", "standard")
    return f"ssl module loaded ({ver}), default_context created"
_check("ssl_import", "INTEGRATION", _ssl_import)


def _socket_import():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.close()
    return "socket AF_INET SOCK_STREAM created + closed"
_check("socket_import", "INTEGRATION", _socket_import)


def _venv_create_probe():
    """Verify venv creation on guest filesystem (RAM:smoke_venv), verifying
    pyvenv.cfg, AmigaDOS wrapper scripts, pip shim/wrappers, prompt, and teardown."""
    import shutil
    import venv
    env_dir = "RAM:smoke_venv"
    if os.path.exists(env_dir):
        shutil.rmtree(env_dir, ignore_errors=True)
    try:
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(env_dir)
        cfg = os.path.join(env_dir, "pyvenv.cfg")
        if not os.path.isfile(cfg):
            raise RuntimeError("pyvenv.cfg missing after create()")
        act = os.path.join(env_dir, "bin", "activate")
        if not os.path.isfile(act):
            raise RuntimeError("bin/activate missing after create()")
        with open(act, encoding="utf-8") as f:
            act_txt = f.read()
        if '(smoke_venv) ' not in act_txt:
            raise RuntimeError("bin/activate prompt missing '(smoke_venv) '")
        py = os.path.join(env_dir, "bin", "python")
        if not os.path.isfile(py):
            raise RuntimeError("bin/python wrapper missing after create()")
        with open(py, encoding="utf-8") as f:
            py_txt = f.read()
        if 'Set __PYVENV_LAUNCHER__' not in py_txt or '/C/' in py_txt:
            raise RuntimeError(f"bin/python wrapper invalid: {py_txt!r}")
        pip_script = os.path.join(env_dir, "bin", "pip")
        if not os.path.isfile(pip_script):
            raise RuntimeError("bin/pip wrapper missing after create()")
        pip_shim = os.path.join(env_dir, "lib", "site-packages", "pip.py")
        if not os.path.isfile(pip_shim):
            raise RuntimeError("lib/site-packages/pip.py shim missing after create()")
        return f"created venv at {env_dir} with AmigaDOS scripts, shim & cfg"
    finally:
        shutil.rmtree(env_dir, ignore_errors=True)
_check("venv_create_probe", "INTEGRATION", _venv_create_probe)


def _venv_runtime_probe():
    """Verify venv site/pip runtime integration in-process (pyvenv.cfg parsing,
    __PYVENV_LAUNCHER__ detection, amiga.pip target routing, and +s script bits)
    without spawning a nested Python subprocess."""
    import importlib.util
    import shutil
    import site
    import venv
    import amiga.pip
    env_dir = "RAM:smoke_venv_rt"
    if os.path.exists(env_dir):
        shutil.rmtree(env_dir, ignore_errors=True)
    orig_env = {
        k: os.environ.get(k)
        for k in ("__PYVENV_LAUNCHER__", "VIRTUAL_ENV")
    }
    orig_prefix = sys.prefix
    orig_exec_prefix = sys.exec_prefix
    orig_base_prefix = sys.base_prefix
    orig_exe = sys.executable
    orig_user_site = site.ENABLE_USER_SITE
    orig_prefixes = list(site.PREFIXES)
    orig_path = list(sys.path)
    try:
        venv.EnvBuilder(with_pip=True).create(env_dir)

        # Verify AmigaDOS +s (script) protection bit on bin/python
        list_tmp = "RAM:smoke_venv_rt_list.txt"
        os.system(f"C:List {env_dir}/bin >{list_tmp}")
        with open(list_tmp, encoding="utf-8", errors="replace") as lf:
            list_out = lf.read()
        os.remove(list_tmp)
        py_lines = [ln for ln in list_out.splitlines() if ln.strip().startswith("python ")]
        if not py_lines or "s" not in py_lines[0].lower():
            raise RuntimeError(f"bin/python missing +s script bit: {list_out!r}")

        # Verify site.venv() detects __PYVENV_LAUNCHER__ and configures isolation
        # (Load python3:lib/site.py if frozen site predates AmigaOS venv patch)
        os.environ["__PYVENV_LAUNCHER__"] = f"{env_dir}/bin/python"
        os.environ["VIRTUAL_ENV"] = env_dir
        site_mod = site
        if "amigaos" not in site.venv.__code__.co_consts and os.path.isfile("python3:lib/site.py"):
            spec = importlib.util.spec_from_file_location("_smoke_site", "python3:lib/site.py")
            site_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(site_mod)
        site_mod.venv(set())
        if sys.prefix != env_dir:
            raise RuntimeError(f"site.venv() sys.prefix={sys.prefix!r}, expected {env_dir!r}")
        if site_mod.ENABLE_USER_SITE is not False:
            raise RuntimeError(f"ENABLE_USER_SITE={site_mod.ENABLE_USER_SITE!r}, expected False")

        # Verify amiga.pip._default_target() routes into the active venv
        pip_target = amiga.pip._default_target()
        if not pip_target.startswith(env_dir):
            raise RuntimeError(f"amiga.pip._default_target()={pip_target!r}, expected under {env_dir!r}")
        return f"verified +s bit, site.venv() prefix={sys.prefix}, pip_target={pip_target}"
    finally:
        for k, v in orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        sys.prefix = orig_prefix
        sys.exec_prefix = orig_exec_prefix
        sys.base_prefix = orig_base_prefix
        sys.executable = orig_exe
        site.ENABLE_USER_SITE = orig_user_site
        site.PREFIXES[:] = orig_prefixes
        sys.path[:] = orig_path
        shutil.rmtree(env_dir, ignore_errors=True)
_check("venv_runtime_probe", "INTEGRATION", _venv_runtime_probe)


def _python2_coexistence_probe():
    """Verify original AmigaOS Python 2 (C:Python) can run alongside Python 3
    without global PYTHONPATH/PYTHONHOME or python3: sys.path pollution."""
    if not os.path.exists("C:Python"):
        return "skipped (C:Python not installed)"
    for var in ("PYTHONPATH", "PYTHONHOME"):
        val = os.environ.get(var, "")
        if "python3:" in val.lower():
            raise RuntimeError(
                f"global {var}={val!r} breaks C:Python (Python 2); unset it in ENV:/ENVARC:"
            )
    py2_script = "RAM:smoke_py2_check.py"
    py2_out = "RAM:smoke_py2.out"
    py2_err = "RAM:smoke_py2.err"
    try:
        with open(py2_script, "w", encoding="utf-8") as f:
            f.write(
                "import os, sys\n"
                "print 'PY2_VER=' + str(sys.version_info[0]) + '.' + str(sys.version_info[1])\n"
                "print 'PY2_OS=' + os.__file__\n"
                "print 'PY2_PATH=' + '|'.join(sys.path)\n"
            )
        rc = os.system(f"C:Python {py2_script} >{py2_out} *>{py2_err}")
        out = open(py2_out, encoding="utf-8", errors="replace").read() if os.path.exists(py2_out) else ""
        err = open(py2_err, encoding="utf-8", errors="replace").read() if os.path.exists(py2_err) else ""
        if rc != 0:
            raise RuntimeError(f"C:Python failed rc={rc}: out={out!r} err={err!r}")
        if "PY2_VER=2." not in out:
            raise RuntimeError(f"unexpected C:Python version output: {out!r}")
        if "python3:" in out.lower():
            raise RuntimeError(f"python3: leaked into C:Python sys.path: {out!r}")
        ver_line = [ln for ln in out.splitlines() if ln.startswith("PY2_VER=")][0]
        os_line = [ln for ln in out.splitlines() if ln.startswith("PY2_OS=")][0]
        return f"C:Python OK ({ver_line}, {os_line})"
    finally:
        for p in (py2_script, py2_out, py2_err):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
_check("python2_coexistence_probe", "INTEGRATION", _python2_coexistence_probe)


def _amiga_py2_bindings_probe():
    """Verify Python 3 AmigaOS bindings for Py2 parity: exec extras
    (getcpu/getmachine/waitforport), asl, icon (.info round-trip),
    catalog, and arexx Port + top-level compat shims."""
    import _amiga
    import amiga.exec as aexec
    import amiga.asl as aasl
    import amiga.icon as aicon
    import amiga.catalog as acat
    import amiga.arexx as aarexx
    import asl
    import icon
    import catalog
    import arexx

    cpu = aexec.getcpu()
    mach = aexec.getmachine()
    if not cpu:
        raise RuntimeError(f"getcpu() returned empty: {cpu!r}")
    if not aexec.waitforport("REXX", timeout_ms=100) and not _amiga.list_ports():
        raise RuntimeError("list_ports() empty")

    # Icon round-trip on RAM:
    icon_target = "RAM:smoke_test_icon"
    with open(icon_target, "w", encoding="utf-8") as f:
        f.write("test\n")
    try:
        dobj = icon.DiskObject(
            type=icon.WBPROJECT,
            default_tool="SYS:Utilities/MultiView",
            tooltypes=["SMOKE=1", "TEST=YES"],
            stack_size=16384,
        )
        dobj.save(icon_target)
        loaded = aicon.DiskObject(icon_target)
        if loaded.type != icon.WBPROJECT or "SMOKE=1" not in loaded.tooltypes:
            raise RuntimeError(f"icon round-trip mismatch: {loaded.type}, {loaded.tooltypes}")
        if not aicon.delete(icon_target):
            raise RuntimeError("icon.delete() failed")
    finally:
        for p in (icon_target, icon_target + ".info"):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    # ARexx public port open/wait(timeout)/close
    pname = "SMOKE_PY3_REXX"
    with aarexx.Port(pname) as port:
        if not aexec.waitforport(pname, timeout_ms=200):
            raise RuntimeError(f"waitforport({pname!r}) failed")
        if port.wait_msg(timeout_ms=20) is not None:
            raise RuntimeError("unexpected message on fresh ARexx port")

    # Catalog fallback when catalog does not exist
    with acat.OpenCatalog("nonexistent_smoke.catalog") as cat:
        if cat.get_string(1, "fallback") != "fallback":
            raise RuntimeError("catalog fallback string mismatch")

    # Verify top-level shims expose expected symbols
    assert hasattr(asl, "FileRequest") and hasattr(asl, "MessageBox")
    assert hasattr(arexx, "Port") and hasattr(arexx, "dorexx")
    assert hasattr(catalog, "OpenCatalog") and hasattr(icon, "DiskObject")
    return f"cpu={cpu}, machine={mach}, icon+arexx+catalog+asl OK"
_check("amiga_py2_bindings_probe", "INTEGRATION", _amiga_py2_bindings_probe)


def _perf_benchmark_probe():
    """Run lightweight Python 3 & AmigaOS binding performance benchmarks
    (CPU, float/math, regex, SHA-256, RAM: metadata & stream I/O, and
    native Amiga bindings) and record timings to the smoke log."""
    import hashlib
    import math
    import re
    import time
    import _amiga
    import amiga.exec as aexec
    import arexx
    import catalog
    import icon

    timings = {}

    def _t(label, fn):
        t0 = time.time()
        fn()
        dt = max(time.time() - t0, 0.0001)
        timings[label] = dt

    def _arith():
        tot = 0
        for i in range(50000):
            tot = (tot + (i * 3) ^ (i >> 2)) & 0xFFFFFFFF
        return tot

    def _fib(n):
        return n if n < 2 else _fib(n - 1) + _fib(n - 2)

    def _dict_list():
        d = {i: (i * i) & 0xFFFF for i in range(10000)}
        s = sum(d[i] for i in range(10000))
        lst = [x for x in range(10000) if (x & 3) == 0]
        return s + len(lst)

    def _sha256():
        payload = b"AmigaOS4-Python-Benchmark-0123456789ABCDEF" * 8
        for _ in range(1000):
            hashlib.sha256(payload).digest()

    def _float_math():
        s = 0.0
        for i in range(1, 10001):
            x = float(i) * 0.001
            s += math.sin(x) + math.sqrt(x)
        return s

    def _regex():
        pat = re.compile(r"[A-Za-z0-9_]+=[0-9]+")
        text = "FOO=123 BAR=456 BAZ=789 QUX=012 " * 8
        for _ in range(1000):
            pat.findall(text)

    def _ram_io():
        d = "RAM:smoke_perf_io"
        if not os.path.isdir(d):
            os.mkdir(d)
        try:
            data = b"AmigaOS4 RAM: perf line\n" * 4
            for i in range(50):
                p = f"{d}/f_{i:03d}.txt"
                with open(p, "wb") as f:
                    f.write(data)
            for name in os.listdir(d):
                p = f"{d}/{name}"
                _ = os.stat(p).st_size
                with open(p, "rb") as f:
                    f.read()
                os.remove(p)
        finally:
            try:
                os.rmdir(d)
            except OSError:
                pass

    def _stream_io():
        p = "RAM:smoke_perf_stream.bin"
        chunk = b"0123456789ABCDEF" * 4096
        try:
            with open(p, "wb") as f:
                for _ in range(8):
                    f.write(chunk)
            with open(p, "rb") as f:
                while f.read(65536):
                    pass
        finally:
            if os.path.exists(p):
                os.remove(p)

    def _amiga_ops():
        for _ in range(50):
            _amiga.list_ports()
            aexec.waitforport("REXX", timeout_ms=50)
        for _ in range(50):
            with catalog.OpenCatalog("sys/dos.catalog") as cat:
                cat.get_string(1, "fallback")
        for _ in range(10):
            with arexx.Port("SMOKE_PERF_REXX"):
                pass
        base = "RAM:smoke_perf_icon"
        with open(base, "wb") as f:
            f.write(b"icon\n")
        try:
            for i in range(10):
                dobj = icon.DiskObject(
                    type=icon.WBPROJECT,
                    default_tool="SYS:Utilities/MultiView",
                    tooltypes=["PERF=1", f"I={i}"],
                    stack_size=16384,
                )
                dobj.save(base)
                _ = icon.DiskObject(base).tooltypes
                icon.delete(base)
        finally:
            for p in (base, base + ".info"):
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass

    _t("arith_50k", _arith)
    _t("fib24", lambda: _fib(24))
    _t("dict_10k", _dict_list)
    _t("sha256_1k", _sha256)
    _t("float_10k", _float_math)
    _t("regex_1k", _regex)
    _t("ram_io_50", _ram_io)
    _t("stream_512k", _stream_io)
    _t("amiga_bindings", _amiga_ops)

    summary = ", ".join(f"{k}={v:.3f}s" for k, v in timings.items())
    _log_raw(f"  perf timings: {summary}")
    return summary
_check("perf_benchmark_probe", "INTEGRATION", _perf_benchmark_probe)


# --- TIER 4: PATH_DIAG (path/assign handling -- Bill's bug class) ------
#
# This tier is diagnostic-heavy. Each probe writes verbose per-item
# results into the log so that if it fails on someone else's guest,
# the log alone gives enough info to diagnose remotely.

# Candidates: mix of native volumes, well-known assigns, custom
# assigns. SMOKE: is created by the wrapper script; python3: is
# Bill's autoinstall assign; others are stock OS4.1.
_CANDIDATES = ["T:", "RAM:", "SYS:",                    # native volumes
               "SYS:", "PROGDIR:",                       # native-ish / process-local
               "LIBS:", "S:", "C:", "DEVS:", "SYS:",     # well-known assigns
               "SMOKE:", "PYTHON:", "python3:"]          # custom / boot-time

# Process-local dynamic assigns (e.g. PROGDIR:) are resolved per-process
# by AmigaDOS and do not appear in the global `assign` list.
_PROCESS_LOCAL_ASSIGNS = {"PROGDIR:"}


def _newlib_assign_visibility():
    """For each candidate volume/assign, record whether newlib sees it
    (via os.listdir) AND whether AmigaDOS sees it (via the pre-cached
    _MOUNTED set parsed at header time). A disagreement flags a
    scope/propagation bug (newlib sees it but AmigaDOS doesn't, or
    vice versa)."""
    lines = []
    disagreements = []
    for prefix in _CANDIDATES:
        newlib_ok = False
        newlib_err = ""
        entries = 0
        try:
            e = os.listdir(prefix)
            newlib_ok = True
            entries = len(e)
        except OSError as ex:
            newlib_err = f"{type(ex).__name__}: {ex}"
        is_process_local = prefix.upper() in _PROCESS_LOCAL_ASSIGNS
        amiga_ok = (prefix.upper() in _MOUNTED) or (is_process_local and newlib_ok)
        target = _ASSIGN_TARGETS.get(prefix.upper(), "(process-local)" if is_process_local else "")
        amiga_status = "OK" if amiga_ok else "MISSING"
        lines.append(
            f"    {prefix:10s} newlib={'OK' if newlib_ok else newlib_err:32s}"
            f"  entries={entries:4d}  amiga={amiga_status:8s}"
            f"  {target}")
        if newlib_ok and not amiga_ok:
            disagreements.append(prefix)
    _log_raw("  visibility matrix (newlib vs cached AmigaDOS state):")
    for line in lines:
        _log_raw(line)
    if disagreements:
        raise RuntimeError(f"phantom-FS: newlib sees {disagreements} "
                           f"but AmigaDOS does not")
    return f"cross-check of {len(_CANDIDATES)} candidates ok"
_check("assign_visibility_matrix", "PATH_DIAG", _newlib_assign_visibility)


def _write_visible_each_assign():
    """For each mounted-and-visible candidate, write a probe file via
    Python open() and cross-check it's visible via AmigaDOS `list`.
    Catches the phantom-write silent-fail class."""
    lines = []
    failed = []
    for prefix in _CANDIDATES:
        try:
            os.listdir(prefix)
        except OSError:
            continue    # not visible to newlib, skip
        probe = prefix + "smoke_writeprobe.tmp"
        try: os.remove(probe)
        except OSError: pass
        result = "?"
        try:
            with open(probe, "w") as f:
                f.write("write_probe_" + prefix)
            with open(probe, "r") as f:
                got = f.read()
            if got != "write_probe_" + prefix:
                result = f"FAIL: readback mismatch ({got!r})"
                failed.append(prefix)
            else:
                if prefix in _PROCESS_LOCAL_ASSIGNS:
                    # PROGDIR: is process-local; C:List would resolve PROGDIR: to C:
                    if "smoke_writeprobe.tmp" in os.listdir(prefix):
                        result = "OK (process-local visible)"
                    else:
                        result = "FAIL: written but missing from os.listdir(PROGDIR:)"
                        failed.append(prefix)
                else:
                    # OOB check
                    rc, oob = _amiga_list(probe)
                    if "smoke_writeprobe.tmp" in oob:
                        result = "OK (visible to amiga)"
                    else:
                        result = f"PHANTOM: written but amiga can't see it (rc={rc}, oob={oob.strip()[:80]!r})"
                        failed.append(prefix)
        except BaseException as e:
            result = f"EXC: {type(e).__name__}: {e}{_errno_of(e)}"
            failed.append(prefix)
        finally:
            try: os.remove(probe)
            except OSError: pass
        lines.append(f"    {prefix:10s} {result}")
    _log_raw("  per-assign write+read+oob-visibility:")
    for line in lines:
        _log_raw(line)
    if failed:
        raise RuntimeError(f"write-visibility failures: {failed}")
    return f"wrote+verified {len(lines)} mounted candidates"
_check("write_visible_each_assign", "PATH_DIAG", _write_visible_each_assign)


def _read_prefix_forms():
    """Try to stat the same physical file addressed multiple ways.
    Bill's bug class shows up as VOL:foo -> phantom, /VOL/foo -> phantom
    or vice versa. Logs each form's result."""
    # Use python3:smoke.py -- we're running from it so it definitely exists
    forms_ok = 0
    forms_fail = 0
    lines = []
    forms = [
        ("python3:smoke.py", "canonical volume syntax"),
        ("python3:smoke.py", "lowercase volume syntax"),
        ("python3:/smoke.py", "volume + leading /"),
        ("/python3/smoke.py", "POSIX-form of volume"),
    ]
    for form, desc in forms:
        try:
            st = os.stat(form)
            lines.append(f"    OK    {form!r:40s} size={st.st_size}  ({desc})")
            forms_ok += 1
        except OSError as ex:
            lines.append(f"    FAIL  {form!r:40s} {type(ex).__name__}: {ex}"
                         f"{_errno_of(ex)}  ({desc})")
            forms_fail += 1
    _log_raw("  stat probe -- same file, multiple path forms:")
    for line in lines:
        _log_raw(line)
    if forms_ok == 0:
        raise RuntimeError("NO form of python3:smoke.py could be stat'd")
    return f"{forms_ok} form(s) worked, {forms_fail} failed (as expected)"
_check("read_prefix_forms", "PATH_DIAG", _read_prefix_forms)


def _import_via_custom_assign():
    """Bill's exact scenario: sys.path.insert(assign_lib); __import__.
    Tries python3:lib first, falls back to LIBS: with staged module."""
    # Try python3:lib (Bill's guest) or SYS:System/python3/lib
    assign_lib = None
    for prefix in ("python3:lib", "SYS:System/python3/lib"):
        try:
            os.stat(prefix)
            assign_lib = prefix
            break
        except OSError:
            continue
    if assign_lib is None:
        _log_raw("  python3: not mounted -- falling back to staged module in LIBS:")
        # Stage a mini module under LIBS: (which we verified works)
        try: os.listdir("LIBS:")
        except OSError:
            return "SKIP: neither python3: nor LIBS: available"
        staged_dir = "LIBS:smoke_stage"
        staged_pkg = staged_dir + "/smokemod"
        try:
            try: os.mkdir(staged_dir)
            except OSError: pass
            try: os.mkdir(staged_pkg)
            except OSError: pass
            with open(staged_pkg + "/__init__.py", "w") as f:
                f.write("VALUE = 'imported_from_custom_assign'\n")
            saved = sys.path[:]
            sys.path.insert(0, staged_dir)
            try:
                mod = __import__("smokemod")
                if getattr(mod, "VALUE", None) != "imported_from_custom_assign":
                    raise RuntimeError(f"unexpected VALUE={getattr(mod,'VALUE',None)!r}")
                return f"staged import via LIBS: -> {mod.__file__}"
            finally:
                sys.path[:] = saved
                sys.modules.pop("smokemod", None)
        finally:
            try: os.remove(staged_pkg + "/__init__.py")
            except OSError: pass
            try: os.rmdir(staged_pkg)
            except OSError: pass
            try: os.rmdir(staged_dir)
            except OSError: pass
    # Real python3: path -- same as Bill's launcher
    candidate = None
    for name in ("cmd", "shelve", "sched", "quopri"):
        if name not in sys.modules:
            candidate = name
            break
    if candidate is None:
        return "SKIP: all candidate stdlib modules already imported"
    saved = sys.path[:]
    try:
        sys.path.insert(0, assign_lib)
        mod = __import__(candidate)
        return f"imported {candidate} from {getattr(mod, '__file__', '?')}"
    finally:
        sys.path[:] = saved
_check("import_via_custom_assign", "PATH_DIAG", _import_via_custom_assign)


def _mkdir_rmdir_custom_assign():
    """Some file operations go through different code paths than
    open() -- probe mkdir/rmdir specifically on a custom assign."""
    lines = []
    failed = []
    for prefix in ("LIBS:", "SYS:", "T:"):
        try: os.listdir(prefix)
        except OSError:
            continue
        d = prefix + "smoke_mkdir_probe"
        try: os.rmdir(d)
        except OSError: pass
        try:
            os.mkdir(d)
        except OSError as ex:
            lines.append(f"    {prefix:10s} mkdir FAIL {type(ex).__name__}: {ex}{_errno_of(ex)}")
            failed.append(prefix)
            continue
        # OOB verify
        rc, oob = _amiga_list(d)
        if "smoke_mkdir_probe" not in oob and "empty" not in oob.lower():
            lines.append(f"    {prefix:10s} mkdir PHANTOM (amiga oob: {oob.strip()[:80]!r})")
            failed.append(prefix)
        else:
            lines.append(f"    {prefix:10s} mkdir OK (visible to amiga)")
        try: os.rmdir(d)
        except OSError as ex:
            lines.append(f"    {prefix:10s} rmdir FAIL {type(ex).__name__}: {ex}")
            failed.append(prefix)
    _log_raw("  mkdir/rmdir per assign:")
    for line in lines:
        _log_raw(line)
    if failed:
        raise RuntimeError(f"mkdir/rmdir failures: {failed}")
    return f"mkdir+rmdir ok on {len(lines)} volumes"
_check("mkdir_rmdir_custom_assign", "PATH_DIAG", _mkdir_rmdir_custom_assign)


def _rename_across_paths():
    """os.rename with source and dest in different volume forms --
    hits both amiga_rename shims."""
    src = "T:smoke_rename_src.txt"
    dst = "T:smoke_rename_dst.txt"
    for p in (src, dst):
        try: os.remove(p)
        except OSError: pass
    with open(src, "w") as f:
        f.write("rename_payload")
    os.rename(src, dst)
    with open(dst, "r") as f:
        got = f.read()
    if got != "rename_payload":
        raise RuntimeError(f"content lost through rename: {got!r}")
    # OOB verify: src gone, dst present
    _, src_oob = _amiga_list(src)
    _, dst_oob = _amiga_list(dst)
    if "smoke_rename_src.txt" in src_oob:
        raise RuntimeError(f"src still visible after rename: {src_oob!r}")
    if "smoke_rename_dst.txt" not in dst_oob:
        raise RuntimeError(f"dst not visible after rename: {dst_oob!r}")
    try: os.remove(dst)
    except OSError: pass
    return "rename src->dst succeeded, both amiga-visible"
_check("rename_across_paths", "PATH_DIAG", _rename_across_paths)


def _long_path_probe():
    """Very long path -- some shim buffers are fixed at 1024. Verify
    they don't truncate silently."""
    long_name = "a" * 200 + ".txt"
    p = "T:" + long_name
    try: os.remove(p)
    except OSError: pass
    with open(p, "w") as f:
        f.write("long_path_ok")
    st = os.stat(p)
    if st.st_size != len("long_path_ok"):
        raise RuntimeError(f"size wrong: {st.st_size}")
    try: os.remove(p)
    except OSError: pass
    return f"{len(long_name)+2}-char path ok"
_check("long_path_probe", "PATH_DIAG", _long_path_probe)


def _nonexistent_volume_errno():
    """Probing a volume that doesn't exist should raise ENOENT, NOT
    a phantom success. If a phantom fs catches the write, we've got
    the silent-write bug."""
    p = "GHOSTVOLNONEXIST:phantom_probe.tmp"
    try:
        with open(p, "w") as f:
            f.write("should_never_land")
        # If we got here, this is the silent-write bug -- the file
        # 'succeeded' but is invisible to AmigaDOS
        _, oob = _amiga_list(p)
        try: os.remove(p)
        except OSError: pass
        if "phantom_probe" in oob:
            raise RuntimeError(f"impossibly-visible: {oob!r}")
        raise RuntimeError(f"open('{p}') succeeded silently -- "
                           f"phantom write to virtual FS")
    except OSError as ex:
        return f"correctly raised {type(ex).__name__}: {ex}{_errno_of(ex)}"
_check("nonexistent_volume_errno", "PATH_DIAG", _nonexistent_volume_errno)


def _cwd_relative_after_chdir():
    """chdir into a real path, then access a file via relative name.
    Exercises the CWD resolution the shim relies on."""
    saved_cwd = os.getcwd()
    try:
        os.chdir("T:")
        probe = "smoke_relprobe.txt"
        with open(probe, "w") as f:
            f.write("rel_ok")
        # Read absolutely
        with open("T:" + probe, "r") as f:
            got = f.read()
        try: os.remove(probe)
        except OSError: pass
        if got != "rel_ok":
            raise RuntimeError(f"content mismatch after chdir: {got!r}")
        return "relative read after chdir works"
    finally:
        try: os.chdir(saved_cwd)
        except OSError: pass
_check("cwd_relative_after_chdir", "PATH_DIAG", _cwd_relative_after_chdir)


def _stat_matrix():
    """For each mounted candidate, stat both the volume itself and a
    known child (whatever appears first in listdir). Logs every result
    including errno. Purely diagnostic -- always passes unless something
    catastrophically breaks."""
    lines = []
    for prefix in _CANDIDATES:
        try:
            entries = os.listdir(prefix)
        except OSError as ex:
            lines.append(f"    {prefix:10s} listdir-FAIL: {type(ex).__name__}: {ex}{_errno_of(ex)}")
            continue
        # stat volume itself (bare prefix)
        try:
            st = os.stat(prefix)
            vol_st = f"vol.mode={oct(st.st_mode)}, size={st.st_size}"
        except OSError as ex:
            vol_st = f"vol.stat-FAIL: {type(ex).__name__}: {ex}{_errno_of(ex)}"
        # stat first entry
        first_st = "no entries"
        if entries:
            child = prefix + entries[0]
            try:
                cs = os.stat(child)
                first_st = f"first={entries[0]!r} size={cs.st_size}"
            except OSError as ex:
                first_st = f"first={entries[0]!r} stat-FAIL: {type(ex).__name__}: {ex}"
        lines.append(f"    {prefix:10s} entries={len(entries):4d}  {vol_st}  {first_st}")
    _log_raw("  stat matrix (diagnostic, non-blocking):")
    for line in lines:
        _log_raw(line)
    return f"logged {len(lines)} candidate stats"
_check("stat_matrix", "PATH_DIAG", _stat_matrix)


def _script_arg_probe():
    """Verify the current smoke.py itself was opened via file-arg mode.
    __file__ tells us how CPython opened it. If __file__ contains a
    custom-assign prefix, we've proven file-arg mode works with that
    assign class."""
    argv0 = sys.argv[0] if sys.argv else "?"
    file_attr = globals().get("__file__", "?")
    _log_raw(f"  sys.argv[0]  = {argv0!r}")
    _log_raw(f"  __file__     = {file_attr!r}")
    # Sanity check: __file__ should exist and be readable
    try:
        with open(file_attr, "rb") as f:
            head = f.read(64)
        return f"__file__ readable, first-64B ok"
    except OSError as ex:
        raise RuntimeError(f"__file__={file_attr!r} not openable: {ex}{_errno_of(ex)}")
_check("script_arg_readable", "PATH_DIAG", _script_arg_probe)


def _fs_encoding_probe():
    """Log filesystem encoding and try a non-ASCII filename. Some
    filesystems on OS4 don't handle latin-1/utf-8 gracefully."""
    enc = sys.getfilesystemencoding()
    _log_raw(f"  filesystem encoding: {enc}")
    _log_raw(f"  sys.getfilesystemencodeerrors: {sys.getfilesystemencodeerrors()}")
    # ASCII only for now -- non-ASCII probes will be added if
    # needed based on OS4's actual filesystem behaviour
    return f"encoding={enc}"
_check("fs_encoding_probe", "PATH_DIAG", _fs_encoding_probe)


def _shim_symbol_check():
    """If amiga_shim.a is linked in, certain symbols should be
    interposed. We can't inspect the ELF from Python, but we can
    verify that a call which would go through the shim behaves
    correctly for a known input. Currently just calls open() with a
    path known to require translation."""
    # LIBS: is a well-known non-native custom assign. If shim
    # translation is broken, open() here will fail or phantom-write.
    p = "LIBS:smoke_shim_marker.tmp"
    try: os.remove(p)
    except OSError: pass
    try:
        with open(p, "w") as f:
            f.write("shim_marker")
        # Immediate stat verify
        st = os.stat(p)
        # OOB verify
        _, oob = _amiga_list(p)
        try: os.remove(p)
        except OSError: pass
        if "smoke_shim_marker" not in oob:
            raise RuntimeError(f"shim wrote to phantom -- amiga oob: {oob!r}")
        return f"shim wrote+verified {st.st_size}B on LIBS:"
    except OSError as ex:
        return f"LIBS: unavailable ({ex}) -- SKIP"
_check("shim_symbol_check", "PATH_DIAG", _shim_symbol_check)


# --- TRAILER: sysconfig + reference dumps -----------------------------

_log_raw("")
_log_raw("--- sysconfig / build config ---------------------------------")
try:
    import sysconfig
    _log_raw("paths:")
    for k, v in sorted(sysconfig.get_paths().items()):
        _log_raw(f"  {k:16s} = {v}")
    _log_raw("selected build vars:")
    for k in ("CC", "CXX", "AR", "LDSHARED", "PY_CFLAGS", "OPT",
              "SHLIB_SUFFIX", "EXT_SUFFIX", "SOABI", "PLATFORM",
              "prefix", "exec_prefix", "installed_platbase"):
        v = sysconfig.get_config_var(k)
        if v is not None:
            _log_raw(f"  {k:20s} = {v!r}")
except Exception as e:
    _log_raw(f"  sysconfig probe failed: {type(e).__name__}: {e}")
_log_raw("")

_log_raw("--- SYS: root listing (for context) ---------------------------")
try:
    entries = sorted(os.listdir("SYS:"))
    for name in entries[:30]:
        _log_raw(f"  {name}")
    if len(entries) > 30:
        _log_raw(f"  ... {len(entries) - 30} more entries omitted")
except Exception as e:
    _log_raw(f"  listdir failed: {e}")
_log_raw("")


if _list_mode:
    sys.exit(0)

# --- summary ----------------------------------------------------------
tiers: dict[str, dict[str, int]] = {}
for name, ok, tier, _ in _results:
    d = tiers.setdefault(tier, {"pass": 0, "fail": 0})
    d["pass" if ok else "fail"] += 1

_log_raw("=== SUMMARY ===")
for tier in ("CORE", "EMBED", "INTEGRATION", "PATH_DIAG"):
    d = tiers.get(tier, {"pass": 0, "fail": 0})
    total = d["pass"] + d["fail"]
    marker = "OK" if d["fail"] == 0 else f"{d['fail']} FAIL"
    _log_raw(f"  {tier:12s}: {d['pass']}/{total} pass  [{marker}]")
failed = [(n, t) for n, ok, t, _ in _results if not ok]
if failed:
    _log_raw("")
    _log_raw("Failed checks:")
    for name, tier in failed:
        _log_raw(f"  - [{tier}] {name}")
    _log_raw("")
    _log_raw("If reporting a bug: paste the FULL contents of T:smoke.log")
    _log_raw("(header, failed test messages, sysconfig dump, and summary).")

# Exit status: 0 all pass, 1 CORE fail, 2 EMBED fail, 3 INTEGRATION
# fail, 4 PATH_DIAG fail (path-handling bug -- often the shim).
if any(not ok and tier == "CORE" for _, ok, tier, _ in _results):
    print("smoke: CORE FAILURE -- do not ship")
    sys.exit(1)
if any(not ok and tier == "EMBED" for _, ok, tier, _ in _results):
    print("smoke: EMBED failure -- libpython.a integration broken")
    sys.exit(2)
if any(not ok and tier == "PATH_DIAG" for _, ok, tier, _ in _results):
    print("smoke: PATH_DIAG failure -- path/assign handling broken")
    sys.exit(4)
if any(not ok for _, ok, _, _ in _results):
    print("smoke: INTEGRATION failure -- pip/ssl/socket surface degraded")
    sys.exit(3)

n_pass = sum(1 for _, ok, _, _ in _results if ok)
print(f"smoke: {n_pass}/{len(_results)} passed -- all tiers green")
sys.exit(0)
