#!/usr/bin/env python3
"""pydiags — OS4 Python diagnostic + config tool.

Two ways to drive it:

  1. **Interactive TUI** (no args): menu-driven browser.  Pick a check
     from the numbered list, see full output.  Type `q` to quit.
         DH1:python-os4 DH1:pytests/examples/pydiags.py
  2. **Headless / scripted** (subcommand arg): run one check + print
     structured output.  Suitable for shelling from another program
     (devbench's amiga_dos_command, an ARexx script, a Startup line).
         DH1:python-os4 DH1:pytests/examples/pydiags.py dns example.com
         DH1:python-os4 DH1:pytests/examples/pydiags.py socket 8.8.8.8 53
         DH1:python-os4 DH1:pytests/examples/pydiags.py env
         DH1:python-os4 DH1:pytests/examples/pydiags.py tasks --top 20
         DH1:python-os4 DH1:pytests/examples/pydiags.py --json ports
         DH1:python-os4 DH1:pytests/examples/pydiags.py setenv KEY VALUE

Every check writes to two streams:

  * stdout          — human summary the user sees.
  * T:pydiags.log   — append-only JSON-lines record of every invocation
                      with args + return code + full output.  Persistent
                      across runs; drives the `pydiags log` subcommand
                      which just tails the last N entries.

Add a new check by writing a `def check_<name>(args) -> dict:` function
below and adding it to REGISTRY.  Interactive + headless discovery is
automatic.
"""
from __future__ import annotations
import json
import os
import re
import socket
import sys
import time

# ---------------------------------------------------------------------------
# Reduced-stdlib guards. Not every environment has _amiga (running this
# on the mac to smoke-test, for example) or every stdlib package.
# ---------------------------------------------------------------------------
try:
    import _amiga
    HAVE_AMIGA = True
except ImportError:
    _amiga = None
    HAVE_AMIGA = False

# Bootstrap amiga.netfix so socket.getaddrinfo / gethostbyname work
# despite newlib's broken resolver on this OS4 build. Best-effort:
# if the package isn't on the path (running pydiags from a workstation
# for smoke tests) we skip silently and rely on the host resolver.
try:
    sys.path.insert(0, "DH1:pytests/amiga_bindings")
    import amiga.netfix     # noqa: F401 — installed as side-effect of import
    HAVE_NETFIX = True
except ImportError:
    HAVE_NETFIX = False


LOG_FILE   = "T:pydiags.log"
CONFIG_DIR = "T:pydiags"
_START_TS  = time.time()


# ---------------------------------------------------------------------------
# Logging + result helper
# ---------------------------------------------------------------------------

def _log_line(kind: str, name: str, args, result: dict) -> None:
    """Append a JSON line to T:pydiags.log."""
    try:
        entry = {
            "ts":     round(time.time(), 3),
            "kind":   kind,
            "check":  name,
            "args":   args,
            "result": result,
        }
        line = json.dumps(entry, default=str) + "\n"
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except OSError:
        pass    # log failures should never break the check itself


def _pretty(result: dict, indent: int = 0) -> str:
    """Human-readable render of a result dict."""
    lines = []
    pad = "  " * indent
    for k, v in result.items():
        if isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(_pretty(v, indent + 1))
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            lines.append(f"{pad}{k}: ({len(v)} entries)")
            for item in v:
                lines.append(_pretty(item, indent + 1))
                lines.append("")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(lines)


def _err(msg: str) -> dict:
    return {"ok": False, "error": msg}


def _ok(**fields) -> dict:
    fields.setdefault("ok", True)
    return fields


# ---------------------------------------------------------------------------
# Checks — every one returns a dict, first key is `ok` bool.
# ---------------------------------------------------------------------------

def check_env(args) -> dict:
    """Environment variables + Python path + working dir."""
    return _ok(
        cwd     = os.getcwd(),
        argv    = sys.argv[:],
        python  = sys.version.split()[0],
        prefix  = sys.prefix,
        exec_prefix = sys.exec_prefix,
        have_amiga    = HAVE_AMIGA,
        have_netfix   = HAVE_NETFIX,
        path    = sys.path[:],
        env     = {k: os.environ[k] for k in sorted(os.environ)
                   if k in ("PYTHONHOME", "PYTHONPATH", "PATH",
                            "USER", "HOME", "SHELL", "TERM",
                            "DISPLAY", "LANG", "LC_ALL")},
    )


def check_hash(args) -> dict:
    """Verify hashlib backends for md5/sha1/sha256/sha512."""
    import hashlib
    out = {"ok": True, "algorithms": {}}
    for algo in ("md5", "sha1", "sha256", "sha512"):
        try:
            h = getattr(hashlib, algo)(b"pydiags")
            out["algorithms"][algo] = h.hexdigest()[:16]
        except Exception as e:
            out["algorithms"][algo] = f"ERR: {type(e).__name__}: {e}"
            out["ok"] = False
    return out


def check_socket(args) -> dict:
    """`pydiags socket <host_or_ip> <port>` — raw TCP connect."""
    if len(args) < 2:
        return _err("usage: socket <host_or_ip> <port>")
    host, port = args[0], int(args[1])
    timeout = float(args[2]) if len(args) >= 3 else 5.0
    s = socket.socket()
    s.settimeout(timeout)
    t0 = time.time()
    try:
        s.connect((host, port))
        dt = int((time.time() - t0) * 1000)
        peer = s.getpeername()
        s.close()
        return _ok(host=host, port=port, peer=list(peer),
                   connect_ms=dt, timeout=timeout)
    except Exception as e:
        return _err(f"{type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")
    finally:
        try: s.close()
        except OSError: pass


def check_dns(args) -> dict:
    """`pydiags dns <hostname>` — 3 lookup methods, whichever survives."""
    if not args:
        return _err("usage: dns <hostname>")
    host = args[0]
    out = {"host": host, "results": {}}

    # 1. socket.gethostbyname
    try:
        out["results"]["gethostbyname"] = socket.gethostbyname(host)
    except Exception as e:
        out["results"]["gethostbyname"] = (
            f"ERR {type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")

    # 2. socket.getaddrinfo
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        out["results"]["getaddrinfo"] = list({i[4][0] for i in infos})
    except Exception as e:
        out["results"]["getaddrinfo"] = (
            f"ERR {type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")

    # 3. Shell out to `ping -c 1 -n <host>` and parse the (IP).
    # OS4 shell doesn't do `2>&1` redirection, and `-q` there requires
    # `=QUIET` explicit; keep it simple.
    tmp = f"T:pydiags_ping.{os.getpid()}"
    rc = os.system(f"ping -c 1 -n {host} >{tmp}")
    try:
        with open(tmp) as f:
            txt = f.read()
    except OSError:
        txt = ""
    finally:
        try: os.remove(tmp)
        except OSError: pass
    m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)", txt)
    out["results"]["ping_resolve"] = m.group(1) if m else f"ERR (rc={rc}) {txt[:120]}"

    out["ok"] = any(not str(v).startswith("ERR") for v in out["results"].values())
    return out


def check_getaddrinfo(args) -> dict:
    """`pydiags getaddrinfo <host> [port]` — isolate whether it works
    on numeric hosts vs names, and whether the AI_NUMERICHOST hint
    changes the answer."""
    if not args:
        return _err("usage: getaddrinfo <host> [port]")
    host = args[0]
    port = int(args[1]) if len(args) >= 2 else 80
    out = {"host": host, "port": port, "attempts": {}}

    def _try(label, *ai_args, **ai_kw):
        try:
            r = socket.getaddrinfo(*ai_args, **ai_kw)
            out["attempts"][label] = [
                {"family": i[0], "socktype": i[1], "proto": i[2],
                 "addr": i[4]} for i in r]
        except Exception as e:
            out["attempts"][label] = (
                f"ERR {type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")

    _try("bare",       host, port)
    _try("AF_INET",    host, port, socket.AF_INET)
    _try("AF_INET+TCP", host, port, socket.AF_INET, socket.SOCK_STREAM, 0)
    _try("NUMERICHOST", host, port, socket.AF_INET, socket.SOCK_STREAM, 0,
         socket.AI_NUMERICHOST)
    _try("NUMERIC+SVC", host, port, socket.AF_INET, socket.SOCK_STREAM, 0,
         socket.AI_NUMERICHOST | socket.AI_NUMERICSERV)

    # Compare with create_connection which urllib uses under the hood.
    try:
        t0 = time.time()
        s = socket.create_connection((host, port), timeout=5.0)
        out["attempts"]["create_connection"] = {
            "ok": True,
            "ms": int((time.time() - t0) * 1000),
            "peer": list(s.getpeername()),
        }
        s.close()
    except Exception as e:
        out["attempts"]["create_connection"] = (
            f"ERR {type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")

    out["ok"] = any(isinstance(v, list) or (isinstance(v, dict) and v.get("ok"))
                    for v in out["attempts"].values())
    return out


def check_http(args) -> dict:
    """`pydiags http <url>` — full urllib.request GET with lazy imports."""
    if not args:
        return _err("usage: http <url>")
    url = args[0]
    timeout = float(args[1]) if len(args) >= 2 else 10.0
    try:
        import urllib.request as _ur
        import urllib.error   as _ue
    except Exception as e:
        return _err(f"urllib import failed: {type(e).__name__}: {e}")
    t0 = time.time()
    try:
        req = _ur.Request(url, headers={"User-Agent": "pydiags/1.0"})
        with _ur.urlopen(req, timeout=timeout) as r:
            body = r.read(4096)
        return _ok(url=url, status=getattr(r, "status", None),
                   content_type=r.headers.get_content_type(),
                   bytes=len(body),
                   ms=int((time.time() - t0) * 1000),
                   preview=body[:200].decode("utf-8", errors="replace"))
    except _ue.HTTPError as e:
        return _err(f"HTTP {e.code}: {e.reason}")
    except _ue.URLError as e:
        return _err(f"URL error: {e.reason}")
    except Exception as e:
        return _err(f"{type(e).__name__} errno={getattr(e, 'errno', None)}: {e}")


def check_ssl(args) -> dict:
    """`pydiags ssl` — check SSL/TLS runtime health.

    Reports each step separately so partial failures are diagnosable:
      - amissl.library openable?  (via `openssl version`)
      - AmiSSL: assign present?
      - `import ssl` works? OPENSSL_VERSION string?
      - amiga.https module importable?
      - end-to-end HTTPS GET via amiga.https to https://example.com/
        (small, predictable, unlikely to change)

    Any step that fails still returns ok=True at the top level with
    per-step results — this is a diagnostic, not a pass/fail gate.
    Callers grepping "ok=True" and ignoring the per-step failures are
    doing it wrong.
    """
    result: dict = {"steps": {}}

    # 1. openssl CLI works? (proves amissl.library loads)
    # AmigaDOS `>file` works for stdout capture; `2>NIL:` gets parsed as
    # a positional arg by openssl and breaks the invocation. Just accept
    # that stderr goes to the console during this check.
    try:
        rc = os.system("DH1:openssl version >T:_ssl_ver")
        with open("T:_ssl_ver", "rb") as f:
            ver_out = f.read().decode("iso-8859-1", errors="replace").strip()
        try: os.remove("T:_ssl_ver")
        except OSError: pass
        result["steps"]["openssl_cli"] = {
            "ok": rc == 0 and ver_out.startswith("OpenSSL"),
            "rc": rc, "version": ver_out,
        }
    except Exception as e:
        result["steps"]["openssl_cli"] = {"ok": False, "err": str(e)}

    # 2. AmiSSL: assign present? (via 'assign LIST AmiSSL:')
    try:
        rc = os.system("assign LIST AmiSSL: >T:_ssl_asg")
        with open("T:_ssl_asg", "rb") as f:
            asg_out = f.read().decode("iso-8859-1", errors="replace")
        try: os.remove("T:_ssl_asg")
        except OSError: pass
        has = "AmiSSL" in asg_out or "AMISSL" in asg_out.upper()
        result["steps"]["amissl_assign"] = {"ok": has, "rc": rc}
    except Exception as e:
        result["steps"]["amissl_assign"] = {"ok": False, "err": str(e)}

    # 3. Python `import ssl` — currently pulls amissl.library at Python
    # startup (task #93 rebuild), so this always succeeds if we got
    # here. After the lazy-load rebuild, this checks whether amissl is
    # actually installed at runtime.
    try:
        import ssl
        result["steps"]["import_ssl"] = {
            "ok": True,
            "openssl_version": ssl.OPENSSL_VERSION,
            "protocols": [p.name for p in ssl.TLSVersion
                         if isinstance(p, ssl.TLSVersion)],
        }
    except ImportError as e:
        result["steps"]["import_ssl"] = {
            "ok": False,
            "err": f"ImportError: {e}",
            "note": "expected without AmiSSL installed if lazy build",
        }
    except Exception as e:
        result["steps"]["import_ssl"] = {
            "ok": False, "err": f"{type(e).__name__}: {e}",
        }

    # 4. amiga.https module importable?
    try:
        import amiga.https as ah
        result["steps"]["import_amiga_https"] = {"ok": True}
    except ImportError as e:
        result["steps"]["import_amiga_https"] = {
            "ok": False, "err": f"ImportError: {e}",
        }
        # Can't do end-to-end without it — bail early.
        return _ok(**result)
    except Exception as e:
        result["steps"]["import_amiga_https"] = {
            "ok": False, "err": f"{type(e).__name__}: {e}",
        }
        return _ok(**result)

    # 5. End-to-end HTTPS GET. example.com is small + stable (RFC 2606
    # reserved for illustrative use; IANA runs a static page there).
    url = args[0] if args else "https://example.com/"
    t0 = time.time()
    try:
        st, hdrs, body = ah.get(url)
        result["steps"]["https_get"] = {
            "ok": st == 200,
            "url": url,
            "status": st,
            "content_type": hdrs.get("content-type", ""),
            "bytes": len(body),
            "ms": int((time.time() - t0) * 1000),
            "preview": body[:120].decode("iso-8859-1", errors="replace"),
        }
    except Exception as e:
        result["steps"]["https_get"] = {
            "ok": False, "url": url,
            "err": f"{type(e).__name__}: {e}",
            "ms": int((time.time() - t0) * 1000),
        }

    # Convenience: are all steps ok?
    result["all_ok"] = all(s.get("ok") for s in result["steps"].values())
    return _ok(**result)


def check_tasks(args) -> dict:
    """List Amiga tasks. --top N to cap."""
    if not HAVE_AMIGA:
        return _err("_amiga not available (not on OS4)")
    top = 20
    if "--top" in args:
        try: top = int(args[args.index("--top") + 1])
        except Exception: pass
    tasks = _amiga.list_tasks()
    tasks_sorted = sorted(tasks, key=lambda t: -t[1])[:top]
    return _ok(total=len(tasks),
               top=[{"name": t[0], "pri": t[1], "state": t[2]}
                    for t in tasks_sorted])


def check_libs(args) -> dict:
    """List Exec libraries with version + open count."""
    if not HAVE_AMIGA:
        return _err("_amiga not available")
    libs = _amiga.list_libraries()
    return _ok(total=len(libs),
               libraries=[{"name": l[0], "version": l[1], "revision": l[2],
                            "opens": l[3]} for l in libs])


def check_ports(args) -> dict:
    """List public message ports + ARexx-looking ones."""
    if not HAVE_AMIGA:
        return _err("_amiga not available")
    all_ports = _amiga.list_ports()
    rexx = _amiga.list_rexx_ports() if hasattr(_amiga, "list_rexx_ports") else []
    return _ok(public_ports=all_ports, arexx_ports=rexx)


def check_mem(args) -> dict:
    """Available memory."""
    if not HAVE_AMIGA:
        return _err("_amiga not available")
    return _ok(**_amiga.avail_mem_summary())


def check_fs(args) -> dict:
    """`pydiags fs [<path>]` — volume info + listing."""
    path = args[0] if args else "DH1:"
    result = {"path": path}
    if HAVE_AMIGA:
        try:
            result["volume_info"] = _amiga.volume_info(path)
        except Exception as e:
            result["volume_info_err"] = f"{type(e).__name__}: {e}"
    try:
        result["entries"] = sorted(os.listdir(path))[:50]
        result["ok"] = True
    except Exception as e:
        result["ok"] = False
        result["error"] = f"{type(e).__name__}: {e}"
    return result


def check_arexx(args) -> dict:
    """Send an ARexx command; `arexx <PORT> <command...>`."""
    if not HAVE_AMIGA or not hasattr(_amiga, "rexx_send"):
        return _err("_amiga.rexx_send not available")
    if len(args) < 2:
        return _err("usage: arexx <PORT_NAME> <command...>")
    port, cmd = args[0], " ".join(args[1:])
    try:
        return _ok(port=port, command=cmd,
                   result=_amiga.rexx_send(port, cmd))
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Config subcommands — actually mutate state.
# ---------------------------------------------------------------------------

def check_setenv(args) -> dict:
    """`pydiags setenv KEY VALUE` — set a shell env var (via os.system)."""
    if len(args) < 2:
        return _err("usage: setenv KEY VALUE")
    key, val = args[0], args[1]
    rc = os.system(f"setenv {key} {val}")
    return _ok(key=key, value=val, setenv_rc=rc,
               readback=os.environ.get(key, "<not visible from this process>"))


def check_assign(args) -> dict:
    """`pydiags assign NAME PATH` — set an AmigaDOS assign."""
    if len(args) < 2:
        return _err("usage: assign NAME PATH")
    name, path = args[0], args[1]
    rc = os.system(f"assign {name}: {path}")
    return _ok(name=name, path=path, rc=rc)


def check_log(args) -> dict:
    """`pydiags log [N]` — tail last N log entries."""
    n = int(args[0]) if args else 20
    try:
        with open(LOG_FILE) as f:
            lines = f.readlines()
    except OSError as e:
        return _err(f"cannot read log: {e}")
    tail = lines[-n:]
    entries = []
    for line in tail:
        try:
            entries.append(json.loads(line))
        except Exception:
            entries.append({"malformed": line.rstrip()})
    return _ok(entries=entries, total_in_file=len(lines))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

REGISTRY = {
    # sanity
    "env":     ("Environment vars + Python config",     check_env),
    "hash":    ("Verify hashlib backends work",         check_hash),
    # networking
    "socket":  ("Raw TCP connect probe",                check_socket),
    "dns":     ("3-way DNS resolution test",            check_dns),
    "getaddrinfo": ("Isolate socket.getaddrinfo variants", check_getaddrinfo),
    "http":    ("HTTP GET via urllib.request",          check_http),
    "ssl":     ("HTTPS/TLS end-to-end sanity",          check_ssl),
    # amiga specific
    "tasks":   ("Amiga task list (top-N by priority)",  check_tasks),
    "libs":    ("Exec libraries + open counts",         check_libs),
    "ports":   ("Public MsgPorts + ARexx ports",        check_ports),
    "mem":     ("Available memory summary",             check_mem),
    "fs":      ("Volume info + directory listing",      check_fs),
    "arexx":   ("Send an ARexx command",                check_arexx),
    # config mutators
    "setenv":  ("Set an env var (side effect)",         check_setenv),
    "assign":  ("Set an AmigaDOS assign (side effect)", check_assign),
    # log
    "log":     ("Tail T:pydiags.log JSON entries",      check_log),
}


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def run_headless(cmd: str, args: list, as_json: bool = False) -> int:
    if cmd not in REGISTRY:
        print(f"unknown check: {cmd}")
        print("known:", ", ".join(sorted(REGISTRY)))
        return 2
    _, fn = REGISTRY[cmd]
    result = fn(args)
    _log_line("headless", cmd, args, result)
    if as_json:
        print(json.dumps(result, default=str, indent=2))
    else:
        print(f"[{cmd}] {'OK' if result.get('ok') else 'FAIL'}")
        print(_pretty(result))
    return 0 if result.get("ok") else 1


def run_tui() -> int:
    entries = sorted(REGISTRY.items())
    ARG_HINTS = {
        "socket":  "host port [timeout]   e.g.: 8.8.8.8 53",
        "dns":     "hostname              e.g.: example.com",
        "getaddrinfo": "host [port]        e.g.: example.com 80",
        "http":    "url [timeout]         e.g.: http://example.com/",
        "ssl":     "[url]                 blank runs default probe (example.com)",
        "arexx":   "PORT command...       e.g.: WORKBENCH SAY 'hi'",
        "setenv":  "KEY VALUE             e.g.: FOO bar",
        "assign":  "NAME PATH             e.g.: MYWORK DH1:work",
        "fs":      "[path]                e.g.: SYS: or blank for DH1:",
        "log":     "[N]                   e.g.: 20 (tail last 20 entries)",
    }
    print("pydiags — interactive TUI.  Enter a number, a check name,")
    print("or `q` to quit.  Every invocation also lands in T:pydiags.log.")
    while True:
        print()
        print("=" * 62)
        print(f" pydiags — {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 62)
        for i, (name, (desc, _)) in enumerate(entries, 1):
            print(f"  {i:>2d}. {name:<12s} {desc}")
        print("   q. quit")
        try:
            choice = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n(stdin closed — exiting.  Try running with a subcommand"
                  " arg for headless mode.)")
            return 0
        if choice in ("q", "quit", "exit"):
            print("bye.")
            return 0
        if not choice:
            continue
        try:
            n = int(choice)
            if not (1 <= n <= len(entries)):
                print(f"out of range (1..{len(entries)})")
                continue
            name = entries[n - 1][0]
        except ValueError:
            if choice in REGISTRY:
                name = choice
            else:
                print(f"unknown check: {choice!r}  (try a number or a name from the list)")
                continue
        # collect extra args interactively for checks that need them
        extra = []
        if name in ARG_HINTS:
            hint = ARG_HINTS[name]
            try:
                raw = input(f"args for {name} ({hint})\n  > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n(no args — running with empty args, will probably show usage)")
                raw = ""
            if raw:
                extra = raw.split()
        _, fn = REGISTRY[name]
        try:
            result = fn(extra)
        except Exception as e:
            import traceback
            result = {"ok": False, "error": f"CRASH: {type(e).__name__}: {e}",
                      "traceback": traceback.format_exc()}
        _log_line("tui", name, extra, result)
        print()
        print("─" * 62)
        print(f" {name}({' '.join(extra)}): {'OK' if result.get('ok') else 'FAIL'}")
        print("─" * 62)
        print(_pretty(result))
        print()
        try:
            input("[Enter to continue, or q+Enter to quit]  ")
        except (EOFError, KeyboardInterrupt):
            return 0


def main() -> int:
    argv = sys.argv[1:]
    as_json = False
    if argv and argv[0] == "--json":
        as_json = True
        argv = argv[1:]
    if not argv:
        return run_tui()
    if argv[0] in ("-h", "--help", "help"):
        print("pydiags — OS4 Python diagnostic tool")
        print("Usage:")
        print("  pydiags.py                        # interactive TUI")
        print("  pydiags.py [--json] <check> [...] # headless subcommand")
        print()
        print("Checks:")
        for name, (desc, _) in sorted(REGISTRY.items()):
            print(f"  {name:<10s} {desc}")
        return 0
    return run_headless(argv[0], argv[1:], as_json=as_json)


if __name__ == "__main__":
    sys.exit(main())
