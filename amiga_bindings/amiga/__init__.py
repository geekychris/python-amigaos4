"""
amiga — Python bindings for AmigaOS 4 APIs.

The package family (dos, exec, intuition, graphics, arexx, bridge)
each specify their public surface; a phase code on each function
tells you which port phase enables its implementation. During Phase
1-4, most calls raise NotImplementedError.

Load `amiga.capabilities()` for a live probe of what's available.
"""
__version__ = "0.1.0-phase2"


def capabilities():
    """Return a dict of {feature: (available: bool, reason: str)}."""
    caps = {}
    # These probes will fill in real answers as later phases land.
    try:
        import _amiga  # noqa: F401
        caps["_amiga extension"] = (True, "loaded")
    except ImportError:
        caps["_amiga extension"] = (False, "phase C not yet implemented")
    try:
        import ctypes  # noqa: F401
        caps["ctypes"] = (True, "loaded")
    except ImportError:
        caps["ctypes"] = (False, "_ctypes not built (phase 3-4)")
    try:
        import socket  # noqa: F401
        caps["socket"] = (True, "loaded")
    except ImportError:
        caps["socket"] = (False, "bsdsocket wrapper not built (phase 3)")
    try:
        import threading  # noqa: F401
        caps["threading"] = (True, "loaded")
    except ImportError:
        caps["threading"] = (False, "pthread shim not built (phase 4)")
    return caps


class NotImplementedYet(NotImplementedError):
    """Convenience exception raised by stubbed functions.

    `phase` is the port phase (2/3/4/5/6/A/B/C) that will implement
    this. Tests check `isinstance(e, NotImplementedYet)` and skip
    accordingly."""
    def __init__(self, phase, feature):
        self.phase = phase
        self.feature = feature
        super().__init__(f"{feature}: not implemented until phase {phase}")
