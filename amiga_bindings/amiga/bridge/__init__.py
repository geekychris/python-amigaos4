"""
amiga.bridge — talk to the amiga-bridge daemon from Python.

The daemon speaks a simple line-based protocol (pipe-delimited
fields, max 1024 chars per line) over serial or TCP. On the OS4
side, our interpreter and the bridge share a machine — so we
connect to `localhost:2345` via bsdsocket.library once Phase 3
lands. See amiga_mcp/amiga-bridge/src/net_io.c for the wire
format from the daemon's perspective.

Phase A landmark: `import amiga.bridge; amiga.bridge.log("info",
"hello")` writes to the bridge log stream, visible from devbench's
web UI + `mcp__amiga-dev__amiga_watch_logs`.
"""
from amiga import NotImplementedYet


def log(level, message):
    """Send a CLOG line to the bridge daemon.

    Args:
        level: "debug" | "info" | "warn" | "error"
        message: any string (multiline OK, will be split)

    Phase A (post-Phase-3): connects to localhost:2345 via socket,
    sends `CLOG|py|<level>|0|<message>\\n`.
    """
    raise NotImplementedYet("A", "amiga.bridge.log")


def exec(command, timeout=30):
    """Run an AmigaDOS command via the bridge's SCRIPT path.

    Returns captured stdout+stderr as str. Times out if the command
    doesn't complete in `timeout` seconds — the bridge will send
    SIGINT to the child.
    """
    raise NotImplementedYet("A", "amiga.bridge.exec")


def screenshot(window=""):
    """Ask the bridge for a screenshot (whole screen or one window).

    Returns raw PNG bytes.
    """
    raise NotImplementedYet("A", "amiga.bridge.screenshot")


def call_hook(client, hook, args=""):
    """Invoke a registered hook on any bridge client.

    Mirrors the MCP `amiga_call_hook` tool but from Python running
    ON the Amiga, useful for scripts that orchestrate other
    bridge-aware apps like Organizer or Masterwork.
    """
    raise NotImplementedYet("A", "amiga.bridge.call_hook")


def get_var(client, name):
    """Read a registered variable by name from any bridge client."""
    raise NotImplementedYet("A", "amiga.bridge.get_var")


def set_var(client, name, value):
    """Write a registered variable by name on any bridge client."""
    raise NotImplementedYet("A", "amiga.bridge.set_var")


def register_var(name, get_fn, set_fn=None):
    """Register a Python callable as a bridge variable.

    Once registered, other bridge clients (including host-side
    devbench MCP tools) can `amiga_get_var(client="pypy", var=name)`
    and get the current value.

    Requires the Python interpreter to be an ab_init'd client, which
    means the pure-Python bridge client needs threading (phase 4)
    to run its poll loop in the background.
    """
    raise NotImplementedYet("A+4", "amiga.bridge.register_var")
