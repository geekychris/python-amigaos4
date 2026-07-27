"""amiga.reaction — thin Python toolkit over BOOPSI classes.

Wraps _amiga.new_object / set_attrs / get_attr / dispose_object so
you can build ReAction-style UIs (button.gadget, string.gadget,
integer.gadget, chooser.gadget, listbrowser.gadget, layout.gadget)
without touching C tag arithmetic.

Basic usage:

    from amiga import reaction as rx

    ok_btn  = rx.Button("OK",     id=1)
    name    = rx.StringGadget(default="",    id=10, max_chars=40)
    age     = rx.IntegerGadget(default=30,   id=11, min=0, max=200)

    layout = rx.LayoutGroup(
        orientation=rx.LAYOUT_ORIENT_VERT,
        children=[
            rx.Labeled("Name:", name),
            rx.Labeled("Age:",  age),
            ok_btn,
        ],
    )

    win = rx.ReactionWindow("New person", layout,
                            width=400, height=200)
    win.open()
    for ev in win.events():
        if ev.get("class") == "close":
            break
        if ev.get("id") == 1:
            print("OK pressed. name=", name.value, "age=", age.value)
            break
    win.close()

Classes returned by every constructor here are lightweight; the real
work is `.handle` (int, the BOOPSI object address). Ownership: the
containing LayoutGroup / ReactionWindow takes over disposal when
attached — don't reuse an object across two windows.
"""
from __future__ import annotations

try:
    import _amiga
except ImportError:
    _amiga = None


# Orientation constants (LAYOUT_Orientation values).
LAYOUT_ORIENT_HORIZ = 0
LAYOUT_ORIENT_VERT  = 1


class BOOPSIObject:
    """Base class — owns a BOOPSI object handle from _amiga.new_object.

    Subclasses set self.CLASS_NAME + a mapping of Python-name → BOOPSI
    tag-name in TAG_MAP so __init__ can translate kwargs.
    """
    CLASS_NAME = ""      # override
    TAG_MAP: dict[str, str] = {}   # override — {py_kwarg: BOOPSI_TAG}

    def __init__(self, **kwargs):
        if _amiga is None:
            raise RuntimeError("_amiga native module not available")
        tags: dict[str, object] = {}
        for py_key, val in kwargs.items():
            tag = self.TAG_MAP.get(py_key)
            if tag is None:
                raise TypeError(f"{type(self).__name__}: unknown kwarg {py_key!r}")
            tags[tag] = val
        self.handle: int = _amiga.new_object(self.CLASS_NAME, tags)
        self._disposed = False

    def set(self, window=0, **kwargs):
        """Update attributes. If window given, uses SetGadgetAttrsA so
        the gadget re-renders; else plain SetAttrsA."""
        tags: dict[str, object] = {}
        for py_key, val in kwargs.items():
            tag = self.TAG_MAP.get(py_key)
            if tag is None:
                raise TypeError(f"{type(self).__name__}: unknown attr {py_key!r}")
            tags[tag] = val
        _amiga.set_attrs(self.handle, tags, window)

    def get_raw(self, tag_name: str) -> int:
        """Raw GetAttr — returns an int (may be a string pointer, another
        BOOPSI object, or a plain integer depending on the tag)."""
        return _amiga.get_attr(self.handle, tag_name)

    def dispose(self):
        if not self._disposed and self.handle:
            _amiga.dispose_object(self.handle)
            self._disposed = True

    def __del__(self):
        # Best-effort — during interpreter shutdown _amiga may already
        # be torn down.
        try: self.dispose()
        except Exception: pass


class Button(BOOPSIObject):
    """A push button. On click emits IDCMP_GADGETUP with GA_ID."""
    CLASS_NAME = "button.gadget"
    TAG_MAP = {
        "text":       "GA_Text",
        "id":         "GA_ID",
        "disabled":   "GA_Disabled",
        "rel_verify": "GA_RelVerify",
    }

    def __init__(self, text, id=0, **kw):
        super().__init__(text=text, id=id, rel_verify=True, **kw)


class StringGadget(BOOPSIObject):
    """Editable text line (string.gadget)."""
    CLASS_NAME = "string.gadget"
    TAG_MAP = {
        "default":   "STRINGA_TextVal",
        "max_chars": "STRINGA_MaxChars",
        "id":        "GA_ID",
        "disabled":  "GA_Disabled",
        "read_only": "GA_ReadOnly",
    }

    def __init__(self, default="", id=0, max_chars=128, **kw):
        super().__init__(default=default, id=id, max_chars=max_chars, **kw)

    @property
    def value(self) -> str:
        """Read the current buffer contents. Underlying GetAttr returns
        an int, which is a pointer to the null-terminated string. We
        can't dereference from Python without ctypes — so use the raw
        pointer as a marker + rely on set_attrs users doing their own
        thing until we add a str-reading helper to _amiga."""
        raw = self.get_raw("STRINGA_TextVal")
        # TODO: dereference the C string via a new _amiga helper. For
        # now callers should snapshot from IDCMP_GADGETUP events which
        # carry the value inline.
        return f"<string@{raw:#x}>"


class IntegerGadget(BOOPSIObject):
    """Bounded integer entry (integer.gadget)."""
    CLASS_NAME = "integer.gadget"
    TAG_MAP = {
        "default":   "INTEGER_Number",
        "min":       "INTEGER_Minimum",
        "max":       "INTEGER_Maximum",
        "id":        "GA_ID",
        "disabled":  "GA_Disabled",
    }

    def __init__(self, default=0, min=None, max=None, id=0, **kw):
        args = {"default": default, "id": id}
        if min is not None: args["min"] = min
        if max is not None: args["max"] = max
        super().__init__(**args, **kw)

    @property
    def value(self) -> int:
        return self.get_raw("INTEGER_Number")


class Chooser(BOOPSIObject):
    """Dropdown / popup list (chooser.gadget)."""
    CLASS_NAME = "chooser.gadget"
    TAG_MAP = {
        "labels":    "CHOOSER_Labels",    # ExecList of Nodes, tricky
        "active":    "CHOOSER_Active",
        "id":        "GA_ID",
        "disabled":  "GA_Disabled",
    }

    @property
    def index(self) -> int:
        return self.get_raw("CHOOSER_Active")


class ListBrowser(BOOPSIObject):
    """Scrollable list of Nodes (listbrowser.gadget)."""
    CLASS_NAME = "listbrowser.gadget"
    TAG_MAP = {
        "labels":       "LISTBROWSER_Labels",
        "column_info":  "LISTBROWSER_ColumnInfo",
        "id":           "GA_ID",
        "disabled":     "GA_Disabled",
    }


class LayoutGroup(BOOPSIObject):
    """A layout container from layout.gadget — the piece that makes
    ReAction resizable-window UIs actually work. Add children with
    .add(child, weight=...) before opening the window."""
    CLASS_NAME = "layout.gadget"
    TAG_MAP = {
        "orientation":    "LAYOUT_Orientation",
        "id":             "GA_ID",
        "space_outer":    "LAYOUT_SpaceOuter",
        "space_inner":    "LAYOUT_SpaceInner",
    }

    def __init__(self, orientation=LAYOUT_ORIENT_HORIZ, children=None, **kw):
        super().__init__(orientation=orientation, **kw)
        self._children: list[BOOPSIObject] = []
        if children:
            for c in children:
                self.add(c)

    def add(self, child: BOOPSIObject):
        """Attach a child gadget. Under the hood: SetAttrs
        LAYOUT_AddChild=child.handle."""
        if not isinstance(child, BOOPSIObject):
            raise TypeError("layout child must be a BOOPSIObject")
        _amiga.set_attrs(self.handle, {"LAYOUT_AddChild": child.handle})
        self._children.append(child)
        return self


def Labeled(label_text: str, gadget: BOOPSIObject) -> BOOPSIObject:
    """Convenience: wraps gadget in a labeled row using LABEL_Text on
    the gadget itself (works for string/integer/chooser). Returns the
    gadget so it fits inline in a children list."""
    _amiga.set_attrs(gadget.handle, {"LAYOUT_Label": label_text})
    return gadget


# --- Menu strip helper ------------------------------------------------------

def install_menus(window_handle: int, spec) -> int:
    """spec = [ (title, [ (item_label, shortcut), None, ... ]) ]
    Returns an mshandle to pass to clear_menus() before close_window."""
    return _amiga.set_menu_strip(window_handle, spec)


def clear_menus(mshandle: int) -> None:
    _amiga.clear_menu_strip(mshandle)


def decode_menu_pick(code: int):
    """(menu, item, sub) tuple from IDCMP_MENUPICK event code."""
    return _amiga.menu_pick_decode(code)
