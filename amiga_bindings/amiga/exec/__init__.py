"""
amiga.exec — exec.library wrappers (task, memory, library, signals).
"""
from amiga import NotImplementedYet


def FindTask(name=None):
    """Find a task/process by name. Returns None if no match.

    Passing name=None returns the current task (this Python interp).
    """
    raise NotImplementedYet("B", "amiga.exec.FindTask")


def list_tasks():
    """Return list of all tasks in the system.

    Each entry: {name, address, priority, state, type: 'task'|'process',
                 signal_mask, cli_command?}"""
    raise NotImplementedYet("B", "amiga.exec.list_tasks")


def AvailMem(flag="any"):
    """Query free memory. flag: 'chip' | 'fast' | 'any' | 'largest'.

    Returns bytes."""
    raise NotImplementedYet("B", "amiga.exec.AvailMem")


def Signal(task, signal_mask):
    """Send signal(s) to a task by bit mask."""
    raise NotImplementedYet("B", "amiga.exec.Signal")


def AllocSignal():
    """Allocate a signal bit. Returns bit number 0-31."""
    raise NotImplementedYet("B", "amiga.exec.AllocSignal")


def Wait(signal_mask):
    """Sleep until any of the given signal bits fire. Returns actual received mask."""
    raise NotImplementedYet("B", "amiga.exec.Wait")


def OpenLibrary(name, version=0):
    """Open a library. Returns opaque handle, or None on failure."""
    raise NotImplementedYet("B", "amiga.exec.OpenLibrary")


def CloseLibrary(handle):
    """Close a previously-opened library."""
    raise NotImplementedYet("B", "amiga.exec.CloseLibrary")


def list_libraries():
    """Enumerate opened libraries. Each entry:

    {name, version, revision, open_count, neg_size, pos_size, id_string}"""
    raise NotImplementedYet("B", "amiga.exec.list_libraries")


def list_ports():
    """List public message ports."""
    raise NotImplementedYet("B", "amiga.exec.list_ports")
