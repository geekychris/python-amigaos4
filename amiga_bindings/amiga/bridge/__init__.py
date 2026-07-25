"""
amiga.bridge — client for the amiga-bridge daemon over TCP.

Speaks the line-based, pipe-delimited text protocol described in
amiga_mcp/amiga-bridge/src/net_io.c.

Phase 3 status:
  Sockets work on OS4 PPC (bsdsocket.library via -lsocket).  The
  daemon accepts one TCP client at a time — so if devbench is
  already connected, opening a bridge from Python here will kick it
  off.  In practice this module is useful when devbench is offline
  or when you want a scripted, headless bridge session.

Connection targets:
    default_endpoint()  →  ("127.0.0.1", 2345) when running on the
                            Amiga itself; overridden by env vars.

Example:
    from amiga.bridge import Bridge
    with Bridge() as b:
        b.log("info", "Hello from Python")
        rc, out = b.script('echo "boo"')
        clients = b.list_clients()
"""
import os
import socket
import time
from collections import namedtuple

from amiga import NotImplementedYet


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

ClientInfo = namedtuple("ClientInfo", "id name pid state")


class BridgeError(Exception):
    """Raised on protocol or transport errors."""


# ---------------------------------------------------------------------------
# Endpoint discovery
# ---------------------------------------------------------------------------

def default_endpoint():
    """Return (host, port) for the bridge daemon.

    Order of resolution:
      1. AMIGA_BRIDGE_HOST + AMIGA_BRIDGE_PORT env vars
      2. When running on Amiga (uname suggests AmigaOS): 127.0.0.1:2345
      3. Fallback: 127.0.0.1:2347 (QEMU port-forward for host-side use)
    """
    host = os.environ.get("AMIGA_BRIDGE_HOST")
    port = os.environ.get("AMIGA_BRIDGE_PORT")
    if host and port:
        return (host, int(port))
    try:
        on_amiga = os.uname().sysname.lower().startswith(("amiga", "aos"))
    except (OSError, AttributeError):
        on_amiga = os.path.exists("SYS:")   # fallback: Amiga volumes visible
    return ("127.0.0.1", 2345 if on_amiga else 2347)


# ---------------------------------------------------------------------------
# Bridge client
# ---------------------------------------------------------------------------

class Bridge:
    """Line-based TCP client for the amiga-bridge daemon.

    Use as a context manager:
        with Bridge() as b:
            b.log("info", "hi")

    Or open explicitly:
        b = Bridge(host="my.host", port=2347)
        b.connect()
        ...
        b.close()
    """

    def __init__(self, host=None, port=None, timeout=5):
        if host is None or port is None:
            h, p = default_endpoint()
            host = host or h
            port = port or p
        self.host = host
        self.port = port
        self.timeout = timeout
        self._sock = None
        self._buf = b""

    # -- lifecycle ----------------------------------------------------------

    def connect(self):
        if self._sock is not None:
            return self
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        s.connect((self.host, self.port))
        self._sock = s
        return self

    def close(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *exc):
        self.close()

    # -- low-level line I/O -------------------------------------------------

    def send_line(self, line):
        """Send one protocol line (no trailing newline needed)."""
        if self._sock is None:
            raise BridgeError("not connected")
        if not line.endswith("\n"):
            line = line + "\n"
        self._sock.sendall(line.encode("utf-8", errors="replace"))

    def recv_line(self, timeout=None):
        """Read one CR/LF-terminated line.  Returns str, or None on EOF/timeout."""
        if self._sock is None:
            raise BridgeError("not connected")
        if timeout is not None:
            self._sock.settimeout(timeout)
        while b"\n" not in self._buf:
            chunk = self._sock.recv(4096)
            if not chunk:
                return None
            self._buf += chunk
        idx = self._buf.index(b"\n")
        line = self._buf[:idx]
        self._buf = self._buf[idx + 1:]
        return line.rstrip(b"\r").decode("utf-8", errors="replace")

    def drain_until(self, prefix, timeout=5):
        """Read lines until one starts with `prefix` — returns that line.
        Ignored lines (mostly async events) are returned in a list alongside.

        Useful for request/response pairs where the daemon may interleave
        heartbeats / CLOG events."""
        others = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.recv_line(timeout=max(0.1, deadline - time.monotonic()))
            if line is None:
                return None, others
            if line.startswith(prefix):
                return line, others
            others.append(line)
        return None, others

    # -- high-level commands ------------------------------------------------

    def log(self, level, message):
        """Emit a CLOG line as if we were a bridge client.  Devbench
        picks this up in the log stream.

        level: 'debug' | 'info' | 'warn' | 'error'
        """
        # CLOG|client|level|tick|message
        safe = message.replace("|", "/").replace("\n", " ")
        self.send_line(f"CLOG|python|{level}|0|{safe}")

    def script(self, script_text, timeout=30):
        """Send SCRIPT|...\\n and drain the daemon's SCRIPT_RESULT reply.

        Returns (rc: int, output: str).  Raises BridgeError on protocol
        error or timeout."""
        safe = script_text.replace("\n", ";").replace("|", "/")
        self.send_line(f"SCRIPT|{safe}")
        line, ignored = self.drain_until("SCRIPT_RESULT", timeout=timeout)
        if line is None:
            raise BridgeError("SCRIPT timeout")
        # SCRIPT_RESULT|rc|output
        parts = line.split("|", 2)
        try:
            rc = int(parts[1])
        except (IndexError, ValueError):
            rc = -1
        out = parts[2] if len(parts) > 2 else ""
        return rc, out

    def list_clients(self, timeout=5):
        """Ask the daemon for its client roster.  Returns [ClientInfo]."""
        self.send_line("LISTCLIENTS")
        line, ignored = self.drain_until("LISTCLIENTS", timeout=timeout)
        if line is None:
            return []
        # LISTCLIENTS|id|name|... — daemon formats vary by version
        parts = line.split("|")[1:]
        clients = []
        # Best-effort: assume each client is (id, name, pid?, state?)
        i = 0
        while i < len(parts):
            slot = parts[i:i + 4] + ["", "", "", ""]
            try:
                cid = int(slot[0])
            except ValueError:
                cid = 0
            clients.append(ClientInfo(id=cid, name=slot[1],
                                       pid=slot[2], state=slot[3]))
            i += 4
        return clients

    def get_var(self, client, name, timeout=5):
        """Read a registered variable from a bridge client."""
        self.send_line(f"GETVAR|{client}|{name}")
        line, _ = self.drain_until("CVAR", timeout=timeout)
        if line is None:
            return None
        # CVAR|client|name|type|value
        parts = line.split("|", 4)
        return parts[4] if len(parts) > 4 else None

    def set_var(self, client, name, value):
        """Write a registered variable on a bridge client."""
        self.send_line(f"SETVAR|{client}|{name}|{value}")

    def call_hook(self, client, hook, args="", timeout=10):
        """Invoke a registered hook on a bridge client.  Returns the
        HOOK_RESULT line's result-field."""
        self.send_line(f"CALLHOOK|{client}|{hook}|{args}")
        line, _ = self.drain_until("HOOK_RESULT", timeout=timeout)
        if line is None:
            return None
        parts = line.split("|", 4)
        return parts[4] if len(parts) > 4 else parts[3] if len(parts) > 3 else ""


# ---------------------------------------------------------------------------
# Module-level convenience wrappers (open + do + close)
# ---------------------------------------------------------------------------

def log(level, message):
    """One-shot log line.  Opens a bridge connection, sends, closes."""
    with Bridge() as b:
        b.log(level, message)


def script(cmd, timeout=30):
    """One-shot script execution."""
    with Bridge() as b:
        return b.script(cmd, timeout=timeout)


def screenshot(window=""):
    """Ask the bridge for a screenshot.  Phase B — the daemon's
    SCREENSHOT protocol returns a large binary blob prefixed by a
    header line, which needs framing support this module hasn't
    added yet."""
    raise NotImplementedYet("A", "amiga.bridge.screenshot (needs binary framing)")


def call_hook(client, hook, args="", timeout=10):
    with Bridge() as b:
        return b.call_hook(client, hook, args, timeout=timeout)


def get_var(client, name):
    with Bridge() as b:
        return b.get_var(client, name)


def set_var(client, name, value):
    with Bridge() as b:
        b.set_var(client, name, value)
