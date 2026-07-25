"""
amiga.intuition — Intuition windows, screens, gadgets, requesters.

Phase A status:
  UI construction on the real screen needs ctypes → intuition.library
  (Phase B) or a native `_amiga` C module (Phase C).  Neither is on
  today's OS4 port.

  BUT — the API surface below models the *paradigm*: OpenWindow /
  IDCMP event flags / GetMsg-drain loops / ReplyMsg / gadget IDs.
  Scripts written against this API can be exercised today in
  simulation mode (AMIGA_INTUITION_SIM=1 env var, default) — a
  print-based fake that logs every UI call — and will flip to real
  Intuition when Phase B/C lands with no source changes.

  A working escape hatch: `EasyRequest` shells out via
  `RequestChoice` (stock OS4 CLI tool) which pops a real Intuition
  requester.  So even in Phase A you can ask the user yes/no from
  Python today.
"""
import os
from collections import namedtuple

from amiga import NotImplementedYet
from amiga.exec import CreateMsgPort, GetMsg, WaitPort, PutMsg


# ---------------------------------------------------------------------------
# IDCMP flags — mirror <intuition/intuition.h>
# ---------------------------------------------------------------------------

IDCMP_CLOSEWINDOW    = 0x00000200
IDCMP_NEWSIZE        = 0x00000002
IDCMP_REFRESHWINDOW  = 0x00000004
IDCMP_MOUSEBUTTONS   = 0x00000008
IDCMP_MOUSEMOVE      = 0x00000010
IDCMP_GADGETUP       = 0x00000040
IDCMP_GADGETDOWN     = 0x00000020
IDCMP_MENUPICK       = 0x00000100
IDCMP_RAWKEY         = 0x00000400
IDCMP_VANILLAKEY     = 0x00200000
IDCMP_ACTIVEWINDOW   = 0x00040000
IDCMP_INACTIVEWINDOW = 0x00080000

# WFLG_* window flags
WFLG_SIZEGADGET     = 0x0001
WFLG_DRAGBAR        = 0x0002
WFLG_DEPTHGADGET    = 0x0004
WFLG_CLOSEGADGET    = 0x0008
WFLG_ACTIVATE       = 0x1000
WFLG_SIMPLE_REFRESH = 0x40


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

ScreenInfo = namedtuple(
    "ScreenInfo",
    "id title width height depth is_public",
)

WindowInfo = namedtuple(
    "WindowInfo",
    "id title left top width height flags idcmp is_active",
)

IntuiEvent = namedtuple(
    "IntuiEvent",
    "kind gadget_id code qualifier mouse_x mouse_y",
)


def _sim():
    """True when running in simulation mode — no real intuition available.
    Default = 1 (sim on) because real Intuition needs Phase B ctypes."""
    return os.environ.get("AMIGA_INTUITION_SIM", "1") == "1"


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

class Screen:
    """A Workbench-style screen.  Phase A: only Workbench pubscreen
    can be 'attached to' (via SIM) — creating custom screens needs Phase B."""

    def __init__(self, title="Workbench", is_public=True):
        self.title = title
        self.is_public = is_public
        self._closed = False

    def close(self):
        self._closed = True

    def to_front(self):
        if _sim():
            print(f"[intu.sim] Screen({self.title!r}).to_front()")
            return True
        raise NotImplementedYet("B", "Screen.to_front (needs intuition ctypes)")

    def to_back(self):
        if _sim():
            print(f"[intu.sim] Screen({self.title!r}).to_back()")
            return True
        raise NotImplementedYet("B", "Screen.to_back")


def LockPubScreen(name="Workbench"):
    """Lock a public screen.  Phase A returns a Screen object marked
    as simulated — real lock happens in Phase B."""
    if _sim():
        print(f"[intu.sim] LockPubScreen({name!r})")
        return Screen(title=name, is_public=True)
    raise NotImplementedYet("B", "LockPubScreen")


def UnlockPubScreen(screen):
    if _sim():
        print(f"[intu.sim] UnlockPubScreen({screen.title!r})")
        return True
    raise NotImplementedYet("B", "UnlockPubScreen")


def list_screens():
    """Enumerate all screens open in the system."""
    if _sim():
        return [ScreenInfo(id=0, title="Workbench", width=800, height=600,
                           depth=24, is_public=True)]
    raise NotImplementedYet("B", "list_screens")


# ---------------------------------------------------------------------------
# Window + IDCMP event loop (the paradigm)
# ---------------------------------------------------------------------------

class Window:
    """An Intuition window.  Constructed with OpenWindow(...).

    Classic Amiga paradigm (WaitPort + GetMsg drain, matches C IDCMP code):

        w = OpenWindow(title="Hi", left=100, top=100, width=400, height=300,
                       idcmp=IDCMP_CLOSEWINDOW | IDCMP_VANILLAKEY)
        running = True
        while running:
            w.wait()                          # block until an event arrives
            for e in w.events():              # drain the port
                if e.kind == "close":
                    running = False
                elif e.kind == "key":
                    handle_key(e.code)
        w.close()

    In simulation, feed synthetic events with `w.post(IntuiEvent(...))`.
    Real events come from the IDCMP port once Phase B lands.
    """

    _next_id = 1

    def __init__(self, title, left, top, width, height, idcmp, flags,
                 screen=None):
        self.id = Window._next_id
        Window._next_id += 1
        self.title = title
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.idcmp = idcmp
        self.flags = flags
        self.screen = screen
        self._port = CreateMsgPort(name=f"WinPort{self.id}")
        self._closed = False
        if _sim():
            print(f"[intu.sim] OpenWindow id={self.id} {title!r} "
                  f"{left},{top} {width}x{height} idcmp=0x{idcmp:x}")

    # -- event handling -----------------------------------------------------

    def wait(self, timeout=None):
        """Block until at least one event is queued.  Doesn't consume —
        pair with `events()` to drain them all."""
        if self._port._queue.empty():
            return self._port._signal.wait(timeout)
        return True

    def events(self):
        """Drain all queued events.  Returns list[IntuiEvent]."""
        out = []
        while True:
            m = GetMsg(self._port)
            if m is None:
                break
            out.append(m.data)
        return out

    def post(self, event):
        """Test / simulation hook: push a synthetic IntuiEvent onto the
        window's port.  Real code doesn't call this — Intuition does."""
        PutMsg(self._port, event)

    # -- drawing / geometry -------------------------------------------------

    def move(self, x, y):
        if _sim():
            print(f"[intu.sim] Win({self.id}).move({x}, {y})")
            self.left, self.top = x, y
            return True
        raise NotImplementedYet("B", "Window.move")

    def size(self, w, h):
        if _sim():
            print(f"[intu.sim] Win({self.id}).size({w}, {h})")
            self.width, self.height = w, h
            return True
        raise NotImplementedYet("B", "Window.size")

    def to_front(self):
        if _sim():
            print(f"[intu.sim] Win({self.id}).to_front()")
            return True
        raise NotImplementedYet("B", "Window.to_front")

    def draw_text(self, x, y, text, pen=1):
        if _sim():
            print(f"[intu.sim] Win({self.id}).draw_text({x},{y},{text!r})")
            return True
        raise NotImplementedYet("B", "Window.draw_text")

    def close(self):
        if not self._closed:
            self._closed = True
            self._port.close()
            if _sim():
                print(f"[intu.sim] CloseWindow id={self.id}")
        return True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def OpenWindow(title="Untitled", left=100, top=100, width=400, height=300,
               idcmp=IDCMP_CLOSEWINDOW,
               flags=WFLG_SIZEGADGET | WFLG_DRAGBAR | WFLG_DEPTHGADGET
                     | WFLG_CLOSEGADGET | WFLG_ACTIVATE | WFLG_SIMPLE_REFRESH,
               screen=None):
    """Create + open an Intuition window."""
    return Window(title, left, top, width, height, idcmp, flags, screen)


def list_windows():
    """Enumerate open windows on the system."""
    if _sim():
        return []
    raise NotImplementedYet("B", "list_windows")


# ---------------------------------------------------------------------------
# Requesters — EasyRequest actually works in Phase A via RequestChoice
# ---------------------------------------------------------------------------

def EasyRequest(title, body, buttons=("OK",)):
    """Pop a modal requester.  Returns the index of the chosen button
    (0-based, though Amiga convention is that button 0 is the rightmost
    / cancel).

    Phase A: shells out to `RequestChoice` (stock OS4 CLI tool that pops
    a real Intuition requester).  Returns int result from stdout."""
    from amiga.dos import _run_capture
    btn_args = " ".join(f'"{b}"' for b in buttons)
    cmd = f'RequestChoice TITLE "{title}" BODY "{body}" GADGETS {btn_args}'
    rc, text = _run_capture(cmd)
    try:
        return int(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def RequestFile(title="Select file", initial_path="", pattern="#?"):
    """Open a file requester.  Phase A: uses `RequestFile` CLI tool."""
    from amiga.dos import _run_capture
    cmd = f'RequestFile TITLE "{title}" PATTERN "{pattern}"'
    if initial_path:
        cmd += f' DRAWER "{initial_path}"'
    rc, text = _run_capture(cmd)
    return text.strip() or None


# ---------------------------------------------------------------------------
# Screenshot — pull the current frame buffer as a bitmap
# ---------------------------------------------------------------------------

def screenshot(path=None):
    """Grab the current Workbench screen.  Phase A: no way to grab
    without ctypes / native.  Bridge-based version arrives when Phase 3
    sockets land — the bridge daemon already implements SCREENSHOT."""
    raise NotImplementedYet("A+4", "amiga.intuition.screenshot (needs bridge socket)")
