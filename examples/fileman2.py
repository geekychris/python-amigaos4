"""fileman2.py — dual-pane file manager rendered as a real ReAction window.

Successor to fileman.py which used _amiga.open_window (classic direct-
OpenWindow). This one composes the UI from window.class +
layout.gadget + listbrowser.gadget entirely through the BOOPSI object
model that _amiga.new_object / new_object_multi / do_method /
lb_make_list wrap.

Layout:
    +---------------- window.class -----------------+
    | HORIZ layout.gadget                            |
    | +----- VERT -----+   +----- VERT -----+       |
    | | left label     |   | right label    |       |
    | | listbrowser    |   | listbrowser    |       |
    | +----------------+   +----------------+       |
    | HORIZ button row: Copy Move Delete Refresh Q  |
    +------------------------------------------------+

Both panes can be local paths or `s3://bucket/prefix` — see the
Pane hierarchy in fileman.py (LocalPane, S3Pane). fileman2 reuses
that model verbatim; only the render layer changes.

Env vars:
    S3_ENDPOINT / S3_ACCESS / S3_SECRET / S3_INSECURE  — S3 config
    FILEMAN2_LEFT   — initial left  path (default SYS:)
    FILEMAN2_RIGHT  — initial right path (default DH1:)
"""
import os
import sys
import time

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga

# Reuse pane model from fileman v1.
sys.path.insert(0, "DH1:pytests/examples")
import fileman as _fm


# ---------------------------------------------------------------- pane wiring

def _rows_from_pane(pane):
    """Convert a Pane's entries into listbrowser rows: (name, size|<DIR>)."""
    rows = []
    for name, is_dir, size, _mtime in pane.entries:
        kind = "<DIR>" if is_dir else str(size)
        rows.append([name, kind])
    return rows


def _refresh_lb(pane, lb_handle, list_slot, win_handle=0):
    """Rebuild the listbrowser rows from the pane's current entries.

    win_handle is passed to set_attrs so the listbrowser knows which
    window to redraw itself in — 0 works pre-open, real handle after
    WM_OPEN. Frees the previous list (if any) and installs a new one.
    list_slot is a one-item list holding the current list handle so
    we can free/replace across refreshes."""
    rows = _rows_from_pane(pane)
    new_list = _amiga.lb_make_list(rows)
    # Detach old list before freeing, otherwise the listbrowser
    # will try to redraw freed nodes.
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": 0}, win_handle)
    if list_slot[0]:
        try:
            _amiga.lb_free_list(list_slot[0])
        except Exception:
            pass
    list_slot[0] = new_list
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": new_list},
                    win_handle)


# ---------------------------------------------------------------- main

def main():
    left_spec  = os.environ.get("FILEMAN2_LEFT",  "SYS:")
    right_spec = os.environ.get("FILEMAN2_RIGHT", "DH1:")

    # Panes provide entries + read_file / write_file / etc. We only
    # use their entries here — the actual file-op wiring lives in
    # fileman.py and can be pulled in in a later iteration.
    class _R: pass
    r = _R(); r.x1=r.y1=r.x2=r.y2=0
    r.w=lambda: 0; r.h=lambda: 0; r.contains=lambda x,y: False
    left  = _fm.make_pane(left_spec,  r, r)
    right = _fm.make_pane(right_spec, r, r)

    # Two panes' listbrowsers each need their own row list.
    left_list_slot  = [None]
    right_list_slot = [None]

    # Build column info once — shared by both listbrowsers.
    cols = _amiga.lb_make_columns([("Name", 200), ("Size", 80)])

    left_lb = _amiga.new_object_multi("listbrowser.gadget", [
        ("GA_ID",                  10),
        ("LISTBROWSER_ColumnInfo", cols),
    ])
    right_lb = _amiga.new_object_multi("listbrowser.gadget", [
        ("GA_ID",                  11),
        ("LISTBROWSER_ColumnInfo", cols),
    ])

    _refresh_lb(left,  left_lb,  left_list_slot)
    _refresh_lb(right, right_lb, right_list_slot)

    left_label  = _amiga.new_object("label.image", {"LABEL_Text": left.path})
    right_label = _amiga.new_object("label.image", {"LABEL_Text": right.path})

    # Buttons — IDs used by GADGETUP dispatch (below).
    b_copy    = _amiga.new_object("button.gadget",
                                   {"GA_ID": 100, "GA_Text": "Copy",
                                    "GA_RelVerify": True})
    b_refresh = _amiga.new_object("button.gadget",
                                   {"GA_ID": 101, "GA_Text": "Refresh",
                                    "GA_RelVerify": True})
    b_quit    = _amiga.new_object("button.gadget",
                                   {"GA_ID": 102, "GA_Text": "Quit",
                                    "GA_RelVerify": True})

    left_pane_layout = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_VERT),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_AddChild",    left_lb),
    ])
    right_pane_layout = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_VERT),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_AddChild",    right_lb),
    ])
    panes_row = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_HORIZ),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_AddChild",    left_pane_layout),
        ("LAYOUT_AddChild",    right_pane_layout),
    ])
    button_row = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_HORIZ),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_AddChild",    b_copy),
        ("LAYOUT_AddChild",    b_refresh),
        ("LAYOUT_AddChild",    b_quit),
    ])
    root = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_VERT),
        ("LAYOUT_SpaceOuter",  True),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_DeferLayout", True),
        ("LAYOUT_AddChild",    panes_row),
        ("LAYOUT_AddChild",    button_row),
    ])

    # Request NEWSIZE events explicitly so the resize-handler below
    # actually fires. Without WA_IDCMP the window defaults miss it.
    idcmp = (_amiga.IDCMP_CLOSEWINDOW
             | _amiga.IDCMP_GADGETUP
             | _amiga.IDCMP_VANILLAKEY
             | _amiga.IDCMP_NEWSIZE)
    win = _amiga.new_object_multi("window.class", [
        ("WA_ScreenTitle",  "Python File Manager v2 (ReAction)"),
        ("WA_Title",        f"{left.path}  |  {right.path}"),
        ("WA_Activate",     True),
        ("WA_DepthGadget",  True),
        ("WA_DragBar",      True),
        ("WA_CloseGadget",  True),
        ("WA_SizeGadget",   True),
        ("WA_IDCMP",        idcmp),
        # Reasonable starting size + generous max so the user can
        # stretch as far as their screen allows.
        ("WA_InnerWidth",   600),
        ("WA_InnerHeight",  400),
        ("WA_MinWidth",     300),
        ("WA_MinHeight",    200),
        ("WA_MaxWidth",     0xFFFFFFFF),
        ("WA_MaxHeight",    0xFFFFFFFF),
        ("WINDOW_Position", _amiga.WPOS_CENTERMOUSE),
        ("WINDOW_Layout",   root),
    ])
    if not win:
        print("fileman2: window object could not be created")
        return 1

    intuiwin = _amiga.do_method(win, _amiga.WM_OPEN)
    if not intuiwin:
        print("fileman2: WM_OPEN returned 0 — window did not open")
        _amiga.dispose_object(win)
        return 1
    print(f"fileman2: window @ {hex(intuiwin)}", flush=True)

    # Event loop — very simple. Every WM_HANDLEINPUT call returns a
    # class + code; we dispatch on class.
    try:
        while True:
            ev = _amiga.wait_message(intuiwin, 5.0)
            if ev is None:
                continue
            cls, code = ev["class"], ev["code"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                break
            if cls == _amiga.IDCMP_VANILLAKEY and code == 27:
                break
            if cls == _amiga.IDCMP_NEWSIZE:
                # User resized the window — tell window.class to
                # re-layout its children to the new client area.
                # Without this, gadgets stay pinned to their
                # NewObject-time geometry and the extra space is
                # ignored.
                # WM_RETHINK = 0x570006 (from classes/window.h);
                # not yet exposed as _amiga.WM_RETHINK — pass raw.
                _amiga.do_method(win, 0x570006)
                continue
            if cls == _amiga.IDCMP_GADGETUP:
                if code == 100:
                    print("fileman2: Copy — not wired yet", flush=True)
                elif code == 101:
                    left.refresh(); right.refresh()
                    _refresh_lb(left,  left_lb,  left_list_slot)
                    _refresh_lb(right, right_lb, right_list_slot)
                    print("fileman2: refreshed", flush=True)
                elif code == 102:
                    break
    finally:
        _amiga.do_method(win, _amiga.WM_CLOSE)
        _amiga.dispose_object(win)
        if left_list_slot[0]:  _amiga.lb_free_list(left_list_slot[0])
        if right_list_slot[0]: _amiga.lb_free_list(right_list_slot[0])
    print("fileman2: bye", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
