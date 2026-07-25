"""
amiga.exec — exec.library wrappers (task, memory, library, signals,
message ports).

Phase A implementation (works today):
  Models the classic Amiga message-passing paradigm using Python
  primitives — `threading.Event` for Signal/Wait, `queue.Queue` for
  MsgPort/PutMsg/GetMsg.  This lets scripts learn and use the
  event-driven pattern that IS Amiga programming, even before Phase C
  wires them onto real dos.CreateMsgPort() / IExec->WaitPort().

  When Phase C lands, the same source will continue to work — the
  classes will bind to real MsgPort structures instead of Python queues.

Phase A also shells out via `os.system("Status >T:...")` for the parts
that need to observe the outside world (list_tasks, AvailMem).

Note: task IDs / signal bits returned from Phase A stubs are
Python-side simulations — do NOT pass them to a real IExec function.
"""
import os
import time
import queue
import threading
from collections import namedtuple

from amiga import NotImplementedYet

# ---------------------------------------------------------------------------
# Optional native backend: _amiga C module (Phase 6).  When present, we call
# straight into IExec/IDOS.  Otherwise fall back to shell-outs.
# ---------------------------------------------------------------------------
try:
    import _amiga as _native
    HAS_NATIVE = True
except ImportError:
    _native = None
    HAS_NATIVE = False


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

TaskInfo = namedtuple(
    "TaskInfo",
    "id name priority state type cli_command",
)

LibraryInfo = namedtuple(
    "LibraryInfo",
    "name version revision open_count",
)


# ---------------------------------------------------------------------------
# Signal + Wait (Phase A: threading.Event-backed)
# ---------------------------------------------------------------------------

class _Signal:
    """A signal bit backed by a threading.Event.  On the real Amiga,
    signal bits are allocated per-task from AllocSignal() (0..31)."""

    _next_bit = 0
    _lock = threading.Lock()

    def __init__(self):
        with _Signal._lock:
            self.bit = _Signal._next_bit
            _Signal._next_bit += 1
        self._event = threading.Event()

    def fire(self):
        self._event.set()

    def wait(self, timeout=None):
        got = self._event.wait(timeout)
        if got:
            self._event.clear()
        return got


def AllocSignal():
    """Allocate a signal bit for the current task.  Returns a
    (bit_number, opaque_handle) pair — the handle is what you pass to
    Signal/Wait."""
    sig = _Signal()
    return sig.bit, sig


def FreeSignal(handle):
    """Release a signal (Phase A: no-op, GC handles it)."""
    return True


def Signal(signal_handle, mask=None):
    """Fire a signal on another task.

    In real Amiga this needs the target Task* and a bit mask.  Phase A
    only supports firing on a handle returned by AllocSignal (i.e. only
    inside a single Python process)."""
    if hasattr(signal_handle, "fire"):
        signal_handle.fire()
        return True
    raise NotImplementedYet("C", "amiga.exec.Signal(cross-task)")


def Wait(signal_handle, timeout=None):
    """Wait until a signal fires.  Returns True on fire, False on
    timeout.  timeout is in seconds; None = forever."""
    if hasattr(signal_handle, "wait"):
        return signal_handle.wait(timeout)
    raise NotImplementedYet("C", "amiga.exec.Wait(other-signal-form)")


# ---------------------------------------------------------------------------
# MsgPort (Phase A: queue.Queue-backed)
# ---------------------------------------------------------------------------

class MsgPort:
    """A message port — receiver end of an inter-task IPC channel.

    Amiga paradigm:
        port = CreateMsgPort("MyPort")
        while running:
            WaitPort(port)                    # blocks until a message arrives
            while (m := GetMsg(port)):        # drain everything queued
                handle(m)
                ReplyMsg(m)                   # if sender expects a reply

    Phase A uses queue.Queue for the buffer and threading.Event for
    the wake-up signal.  This works within a single Python process
    only; cross-task on the real Amiga arrives in Phase C.
    """

    _public_ports = {}
    _public_lock = threading.Lock()

    def __init__(self, name=None, public=False):
        self.name = name
        self.public = public
        self._queue = queue.Queue()
        self._wake = threading.Event()
        self._signal_bit, self._signal = AllocSignal()
        if public and name:
            with MsgPort._public_lock:
                MsgPort._public_ports[name] = self

    def close(self):
        if self.public and self.name:
            with MsgPort._public_lock:
                MsgPort._public_ports.pop(self.name, None)

    @property
    def signal_bit(self):
        """The signal bit that fires when a new message arrives —
        pass to Wait() as part of a signal mask on real Amiga."""
        return self._signal_bit


class Message:
    """A single message on a MsgPort.  Any Python object can be the
    payload; the wrapper carries reply-port bookkeeping."""

    def __init__(self, data, reply_port=None):
        self.data = data
        self.reply_port = reply_port
        self._replied = False

    def reply(self, response=None):
        """Send back a reply message on the reply_port (if any)."""
        if self._replied:
            return False
        self._replied = True
        if self.reply_port is None:
            return False
        PutMsg(self.reply_port, response if response is not None else self.data)
        return True


def CreateMsgPort(name=None, public=False):
    """Create a MsgPort.  public=True registers it under `name` so other
    tasks can FindPort() it."""
    return MsgPort(name=name, public=public)


def DeleteMsgPort(port):
    """Tear down a MsgPort."""
    port.close()
    return True


def FindPort(name):
    """Locate a public MsgPort by name.  Returns None if not found."""
    with MsgPort._public_lock:
        return MsgPort._public_ports.get(name)


def PutMsg(port, data, reply_port=None):
    """Send a message to a port.  If reply_port is given, the sender
    can await a reply on it."""
    msg = Message(data, reply_port=reply_port)
    port._queue.put(msg)
    port._signal.fire()
    return msg


def GetMsg(port):
    """Non-blocking receive.  Returns Message or None if empty."""
    try:
        return port._queue.get_nowait()
    except queue.Empty:
        return None


def WaitPort(port, timeout=None):
    """Block until at least one message is on the port.  Returns the
    first Message (doesn't remove others — drain with GetMsg())."""
    if port._queue.empty():
        got = port._signal.wait(timeout)
        if not got:
            return None
    return GetMsg(port)


def ReplyMsg(msg, response=None):
    """Convenience for msg.reply(response)."""
    return msg.reply(response)


# ---------------------------------------------------------------------------
# Task / process introspection
# ---------------------------------------------------------------------------

def FindTask(name=None):
    """Return TaskInfo for a task by name; None if no match.  With
    name=None, returns info about the current Python task.

    Uses _amiga.find_task when the native module is available;
    otherwise falls back to a threading-based approximation."""
    if HAS_NATIVE:
        got = _native.find_task(name)
        if got is None:
            return None
        nm, pri, addr = got
        return TaskInfo(id=addr, name=nm, priority=pri,
                        state="Ready", type="task", cli_command="")
    if name is None:
        try:
            tid = os.getpid()
        except OSError:
            tid = 0
        return TaskInfo(id=tid, name="python", priority=0,
                        state="Ready", type="process", cli_command="")
    for t in list_tasks():
        if t.name == name:
            return t
    return None


def list_tasks():
    """Enumerate tasks in the system.

    Native path: walks ExecBase->TaskReady + TaskWait via _amiga.list_tasks.
    Fallback path: shells out to the `Status FULL` DOS command and parses."""
    if HAS_NATIVE:
        return [TaskInfo(id=0, name=n, priority=p, state=s,
                         type="task", cli_command="")
                for (n, p, s) in _native.list_tasks()]

    from amiga.dos import _run_capture
    rc, text = _run_capture("Status FULL")
    if rc != 0:
        return []
    tasks = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("Process", "-", "=")):
            continue
        if s.lower().startswith("process") and ":" in s:
            head, _, rest = s.partition(":")
            try:
                pid = int(head.split()[1])
            except (IndexError, ValueError):
                pid = 0
            cmd = ""
            if "command:" in rest:
                cmd = rest.split("command:", 1)[1].strip()
            tasks.append(TaskInfo(id=pid, name=cmd or f"proc{pid}",
                                  priority=0, state="Ready",
                                  type="process", cli_command=cmd))
    return tasks


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def AvailMem(flag="any"):
    """Query free memory via `Avail`.  Returns bytes."""
    from amiga.dos import _run_capture
    rc, text = _run_capture("Avail")
    if rc != 0:
        return 0
    # Avail output looks like:
    #     Type         Available     In-Use    Maximum   Largest
    #     public    ...
    # We just want the total 'free' column for the type asked.
    row = {"any": "total", "chip": "chip", "fast": "fast"}.get(flag, flag)
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower() == row and len(parts) >= 2:
            try:
                return int(parts[1].replace(",", ""))
            except ValueError:
                pass
    return 0


# ---------------------------------------------------------------------------
# Libraries
# ---------------------------------------------------------------------------

def OpenLibrary(name, version=0):
    """Open a shared library.  Phase A can't actually open Amiga libs,
    but we return a synthetic handle so scripts learn the API."""
    raise NotImplementedYet("B", "amiga.exec.OpenLibrary (needs ctypes)")


def CloseLibrary(handle):
    """Close a library opened by OpenLibrary."""
    raise NotImplementedYet("B", "amiga.exec.CloseLibrary")


def list_libraries():
    """Enumerate opened libraries via the `Version >T:...` command's
    library listing."""
    raise NotImplementedYet("B", "amiga.exec.list_libraries (needs ExecBase walk)")


def list_ports():
    """List public message ports.  Phase A returns our own PYTHON-side
    ports registered via MsgPort(public=True) — cross-process comes with
    Phase C."""
    with MsgPort._public_lock:
        return list(MsgPort._public_ports.keys())
