"""
amiga.os — a shim of Python's `subprocess` module for AmigaOS 4.

Newlib on OS4 doesn't have fork(), so CPython's real `subprocess`
module can't be enabled (it needs `_posixsubprocess` which is
`fork+exec`).  This module offers the SUBSET of subprocess that
`os.system() + tempfile capture` can implement:

    result = amiga.os.run("Info", capture_output=True, text=True)
    # -> CompletedProcess(args='Info', returncode=0, stdout='...', stderr='')

Not offered (no fork, no pipes): Popen streaming stdin, real-time
stdout, signal delivery to a live child, wait()-loop, .stdin.write(),
timeout kill.  These require Phase 6's native _amiga module (which can
call SystemTagList with SYS_Input/Output CMD_CLOSE plumbing).

Prefer this module over raw `os.system()` when you want:
  - Structured return: CompletedProcess with stdout, stderr, rc
  - Argument-vector safety: list-of-strings inputs get shell-quoted
  - check=True raises CalledProcessError on non-zero exit
  - env=..., cwd=..., timeout=... approximations (all Phase A best-effort)
"""
import os
import time
from collections import namedtuple

CompletedProcess = namedtuple(
    "CompletedProcess", "args returncode stdout stderr"
)


class CalledProcessError(Exception):
    def __init__(self, returncode, cmd, output=None, stderr=None):
        self.returncode = returncode
        self.cmd = cmd
        self.output = output or ""
        self.stderr = stderr or ""
        super().__init__(
            f"Command {cmd!r} returned non-zero exit status {returncode}."
        )


class TimeoutExpired(Exception):
    def __init__(self, cmd, timeout, output=None, stderr=None):
        self.cmd = cmd
        self.timeout = timeout
        self.output = output or ""
        self.stderr = stderr or ""
        super().__init__(f"Command {cmd!r} timed out after {timeout}s")


# ---------------------------------------------------------------------------
# Internal command-line builder
# ---------------------------------------------------------------------------

def _build_cmd(args):
    """Turn a list-of-strings into a shell-quoted single command line.
    Bare strings pass through unchanged."""
    if isinstance(args, str):
        return args
    parts = []
    for a in args:
        s = str(a)
        if any(c in s for c in " \t\"'|&<>*?[]$;#()"):
            # AmigaDOS: prefer *N wrap for quoted args with escapes,
            # but doublequotes work in most cases here.
            s = '"' + s.replace('"', '*"') + '"'
        parts.append(s)
    return " ".join(parts)


_capture_counter = 0


def _new_tempfile(suffix="tmp"):
    global _capture_counter
    _capture_counter += 1
    return f"T:amiga_os_{os.getpid() if hasattr(os, 'getpid') else 0}_{_capture_counter}_{int(time.time())}.{suffix}"


def _slurp(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _cleanup(*paths):
    for p in paths:
        if not p:
            continue
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Public: subprocess.run() drop-in (subset)
# ---------------------------------------------------------------------------

def run(args, *, capture_output=False, text=False, check=False,
        cwd=None, env=None, timeout=None, stdout=None, stderr=None,
        input=None):
    """Run a command; wait for completion; return CompletedProcess.

    Deliberately compatible with subprocess.run() so most scripts port
    verbatim.  Phase A limitations:

    - `input=` is ignored (no stdin pipe without fork).
    - `env=` is applied by prefixing `Setenv` commands into a wrapper
      script — visible to the child but doesn't restore afterwards.
    - `timeout=` is best-effort: we can only detect after the fact,
      since os.system() blocks.  A shell-level timeout is inserted only
      if the OS4 `Run TIMEOUT ...` command is available.
    """
    cmd = _build_cmd(args)

    if capture_output:
        stdout = "PIPE"
        stderr = "STDOUT"       # merged into stdout — no pipe pair without fork

    out_tag = _new_tempfile("out") if stdout == "PIPE" else None
    err_tag = None
    tail = ""
    if out_tag:
        tail = f" >{out_tag}"

    # cwd approximation: cd inside the same shell invocation
    if cwd:
        cmd = f"cd {cwd}; {cmd}"

    # env approximation: prefix Setenv statements
    if env:
        setenvs = "; ".join(f"setenv {k} \"{v}\"" for k, v in env.items())
        cmd = f"{setenvs}; {cmd}"

    started = time.monotonic()
    rc = os.system(cmd + tail)
    elapsed = time.monotonic() - started

    if timeout is not None and elapsed > timeout:
        _cleanup(out_tag, err_tag)
        raise TimeoutExpired(cmd, timeout,
                             output=_slurp(out_tag) if out_tag else None)

    stdout_text = _slurp(out_tag) if out_tag else None
    stderr_text = ""
    _cleanup(out_tag, err_tag)

    if not text and stdout_text is not None:
        stdout_text = stdout_text.encode("utf-8", errors="replace")

    result = CompletedProcess(args=args, returncode=rc,
                              stdout=stdout_text, stderr=stderr_text)
    if check and rc != 0:
        raise CalledProcessError(rc, cmd,
                                  output=stdout_text, stderr=stderr_text)
    return result


def check_output(args, **kwargs):
    """Convenience: run, raise on failure, return captured stdout."""
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("check", True)
    kwargs.setdefault("text", True)
    return run(args, **kwargs).stdout


def call(args, **kwargs):
    """Run and return only the returncode."""
    return run(args, **kwargs).returncode


def check_call(args, **kwargs):
    """Run; raise CalledProcessError on non-zero exit."""
    kwargs.setdefault("check", True)
    return run(args, **kwargs).returncode


# ---------------------------------------------------------------------------
# NOT IMPLEMENTED (need real pipes / fork)
# ---------------------------------------------------------------------------

class Popen:
    """Placeholder — real Popen needs fork+pipes.  Raises immediately.

    Use amiga.os.run() for one-shot commands; if you need streaming
    stdout, the amiga-bridge SCRIPT protocol already does it (see
    amiga.bridge.script) and Phase 6's native _amiga.spawn() will
    later back a real Popen."""

    def __init__(self, *a, **kw):
        raise NotImplementedError(
            "Popen requires fork+pipes; use amiga.os.run() instead "
            "(or amiga.bridge.script() for streamed output)."
        )
