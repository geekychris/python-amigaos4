"""
amiga.intuition — window / screen / requester wrappers.
"""
from amiga import NotImplementedYet


def list_screens():
    """Return list of open Intuition screens.

    Each entry: {title, width, height, depth, is_public, position}
    """
    raise NotImplementedYet("B", "amiga.intuition.list_screens")


def list_windows(screen_name=None):
    """Return list of open windows (optionally filtered to one screen).

    Each entry: {title, screen, x, y, width, height, has_border,
                 gadgets: [...], flags: [...]}"""
    raise NotImplementedYet("B", "amiga.intuition.list_windows")


def LockPubScreen(name="Workbench"):
    """Get a lock on a named public screen. Returns opaque handle."""
    raise NotImplementedYet("B", "amiga.intuition.LockPubScreen")


def UnlockPubScreen(name, screen):
    """Release the lock."""
    raise NotImplementedYet("B", "amiga.intuition.UnlockPubScreen")


def OpenWindow(**kwargs):
    """Open a window. Accepts Amiga WA_* tags as kwargs:

    left, top, width, height, title, screen, flags, idcmp, ...
    """
    raise NotImplementedYet("B/C", "amiga.intuition.OpenWindow")


def EasyRequest(title, body, gadgets="OK", **args):
    """Pop up an EasyRequester dialog.

    Returns index of clicked gadget (0 = leftmost/default, 1 = next, ...)
    """
    raise NotImplementedYet("B", "amiga.intuition.EasyRequest")


def MoveWindow(window, dx, dy):
    """Move an open window by (dx, dy) pixels."""
    raise NotImplementedYet("B", "amiga.intuition.MoveWindow")


def SizeWindow(window, dw, dh):
    """Resize an open window by (dw, dh) pixels."""
    raise NotImplementedYet("B", "amiga.intuition.SizeWindow")


def WindowToFront(window):
    """Bring a window to the top of its screen's z-order."""
    raise NotImplementedYet("B", "amiga.intuition.WindowToFront")


def screenshot(what="screen"):
    """Capture screen or window pixels as raw bytes.

    what: "screen" (whole screen) or a window title.
    Returns: (width, height, depth, pixel_bytes)
    """
    raise NotImplementedYet("B/C", "amiga.intuition.screenshot")
