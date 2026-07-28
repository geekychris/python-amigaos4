"""fileman2.py — dual-pane file manager rendered as a real ReAction window.

Successor to fileman.py which used _amiga.open_window (classic direct-
OpenWindow). This one composes the UI from window.class +
layout.gadget + listbrowser.gadget entirely through the BOOPSI object
model that _amiga.new_object / new_object_multi / do_method /
lb_make_list wrap.

Layout:
    +----- window.class (resizable, WM_RETHINK on NEWSIZE) -----+
    | HORIZ layout.gadget                                        |
    | +----- VERT -----+   +----- VERT -----+                   |
    | | left listbrw   |   | right listbrw  |                   |
    | +----------------+   +----------------+                   |
    | HORIZ FixedVert: Set Copy Refresh MkBucket Quit           |
    +------------------------------------------------------------+

Both panes can be local paths OR `s3://[bucket[/prefix]]`. Env
vars set the initial targets and S3 creds:

    S3_ENDPOINT / S3_ACCESS / S3_SECRET / S3_INSECURE  — S3 config
    FILEMAN2_LEFT   — initial left  path (default SYS:)
    FILEMAN2_RIGHT  — initial right path (default DH1:)

For the local MinIO on the host, `execute DH1:s3cli/s3-env-local`
then set FILEMAN2_RIGHT to `s3://` and rerun to browse buckets.

Buttons:
  Set       — prompt for a new path for the focused pane
  Copy      — read selected file from focused pane, write to other
  Refresh   — re-list both panes
  MkBucket  — when focused pane is on `s3://` (bucket list), prompt
              for a name and create the bucket
  Quit      — close
"""
import os
import sys
import time

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga

# Reuse pane model from fileman v1.
sys.path.insert(0, "python3:examples")
import fileman as _fm


# --- Diagnostic logger --------------------------------------------------
# `run` on AmigaDOS detaches from the CLI's stdout, and `>RAM:fm2.log`
# on the run line only captures run's own output, not the child's
# print(). So we log everything to a file ourselves. Overwrites at
# startup; `type RAM:fm2.log` after any UI action to see the trace.

_LOG_PATH = "RAM:fm2.log"
try:
    _log_fp = open(_LOG_PATH, "w")
except Exception:
    _log_fp = None

def _log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    try:
        print(line, flush=True)
    except Exception:
        pass
    if _log_fp:
        try:
            _log_fp.write(line + "\n")
            _log_fp.flush()
        except Exception:
            pass

# Monkey-patch print so any accidental print() calls also hit the log.
_orig_print = print
def print(*a, **kw):        # noqa: A001
    _orig_print(*a, **kw)
    if _log_fp:
        try:
            msg = " ".join(str(x) for x in a)
            _log_fp.write(msg + "\n")
            _log_fp.flush()
        except Exception:
            pass


# ---------------------------------------------------------------- IDs

ID_LB_LEFT     = 10
ID_LB_RIGHT    = 11
ID_BTN_SET     = 100
ID_BTN_COPY    = 101
ID_BTN_REFRESH = 102
ID_BTN_MKB     = 103
ID_BTN_QUIT    = 104


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
    WM_OPEN."""
    rows = _rows_from_pane(pane)
    new_list = _amiga.lb_make_list(rows)
    # Detach old list before freeing to avoid a redraw on freed nodes.
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": 0}, win_handle)
    if list_slot[0]:
        try:
            _amiga.lb_free_list(list_slot[0])
        except Exception:
            pass
    list_slot[0] = new_list
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": new_list},
                    win_handle)


# ---------------------------------------------------------------- dialogs

def _prompt(title, label, default="", maxlen=200):
    if not hasattr(_amiga, "open_dialog"):
        return default
    h = _amiga.open_dialog(title=title,
                            fields=[(label, default, maxlen)],
                            ok_label="OK", cancel_label="Cancel",
                            left=200, top=140)
    try:
        r = _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)
    if r is None:
        return None
    return r.get(label, default)


# ---------------------------------------------------------------- main

def main():
    left_spec  = os.environ.get("FILEMAN2_LEFT",  "SYS:")
    right_spec = os.environ.get("FILEMAN2_RIGHT", "DH1:")
    if not right_spec.startswith("s3://") and not os.path.exists(right_spec):
        right_spec = "SYS:"

    class _R: pass
    r = _R(); r.x1=r.y1=r.x2=r.y2=0
    r.w=lambda: 0; r.h=lambda: 0; r.contains=lambda x,y: False
    panes = {
        "left":    _fm.make_pane(left_spec,  r, r),
        "right":   _fm.make_pane(right_spec, r, r),
        "focused": "left",
    }

    left_list_slot  = [None]
    right_list_slot = [None]

    # Column info once — shared by both listbrowsers.
    cols = _amiga.lb_make_columns([("Name", 200), ("Size", 80)])

    # Listbrowser flags — the important one is LISTBROWSER_ShowSelected
    # which draws the selected-row highlight. Default is FALSE — a
    # click still SETS internal selection but there's no visible
    # feedback and it looks like nothing happened. AutoFit expands
    # to fit the pane width. ColumnTitles hides the column-title bar
    # (we don't need it — columns are just Name / Size). MultiSelect
    # off = single-select; on = ctrl-click adds to selection.
    # (Raw ints because these are not yet in _amigamodule.c TAG_TABLE
    # — add on the next rebuild for cleanliness.)
    _LISTBROWSER_MultiSelect  = 0x85003006
    _LISTBROWSER_AutoFit      = 0x85003010
    _LISTBROWSER_ColumnTitles = 0x85003011
    _LISTBROWSER_ShowSelected = 0x85003012
    _lb_common = [
        ("LISTBROWSER_ColumnInfo", cols),
        (_LISTBROWSER_AutoFit,      True),
        (_LISTBROWSER_ShowSelected, True),
        (_LISTBROWSER_ColumnTitles, False),
    ]
    left_lb  = _amiga.new_object_multi("listbrowser.gadget",
                                        [("GA_ID", ID_LB_LEFT)]  + _lb_common)
    right_lb = _amiga.new_object_multi("listbrowser.gadget",
                                        [("GA_ID", ID_LB_RIGHT)] + _lb_common)

    _refresh_lb(panes["left"],  left_lb,  left_list_slot)
    _refresh_lb(panes["right"], right_lb, right_list_slot)

    # Buttons — ID_BTN_* values feed the GADGETUP dispatch below.
    def _mkbtn(bid, label):
        return _amiga.new_object("button.gadget",
                                  {"GA_ID": bid, "GA_Text": label,
                                   "GA_RelVerify": True})

    b_set     = _mkbtn(ID_BTN_SET,     "Set")
    b_copy    = _mkbtn(ID_BTN_COPY,    "Copy")
    b_refresh = _mkbtn(ID_BTN_REFRESH, "Refresh")
    b_mkb     = _mkbtn(ID_BTN_MKB,     "MkBucket")
    b_quit    = _mkbtn(ID_BTN_QUIT,    "Quit")

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
    # Button row height is controlled by CHILD_WeightedHeight=0 on
    # the parent's LAYOUT_AddChild for this row (see root layout
    # below) — LAYOUT_FixedVert doesn't do what its name suggests
    # here.
    button_row = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_HORIZ),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_EvenSize",    True),          # buttons same width
        ("LAYOUT_AddChild",    b_set),
        ("LAYOUT_AddChild",    b_copy),
        ("LAYOUT_AddChild",    b_refresh),
        ("LAYOUT_AddChild",    b_mkb),
        ("LAYOUT_AddChild",    b_quit),
    ])
    # CHILD_WeightedHeight (raw 0x85007106 = LAYOUT_Dummy+0x100+6, from
    # gadgets/layout.h) is a per-child sizing hint that layout.gadget
    # reads immediately after the LAYOUT_AddChild it follows. Default
    # is 100; 0 means "lock this child at its minimum height and give
    # all extra vertical space to siblings." That's what makes the
    # button row stay one-row-tall instead of eating half the window.
    _CHILD_WeightedHeight = 0x85007106
    root = _amiga.new_object_multi("layout.gadget", [
        ("LAYOUT_Orientation", _amiga.LAYOUT_ORIENT_VERT),
        ("LAYOUT_SpaceOuter",  True),
        ("LAYOUT_SpaceInner",  True),
        ("LAYOUT_DeferLayout", True),
        ("LAYOUT_AddChild",    panes_row),
        (_CHILD_WeightedHeight, 100),          # panes_row: absorb space
        ("LAYOUT_AddChild",    button_row),
        (_CHILD_WeightedHeight, 0),            # button_row: min height
    ])

    idcmp = (_amiga.IDCMP_CLOSEWINDOW
             | _amiga.IDCMP_GADGETUP
             | _amiga.IDCMP_VANILLAKEY
             | _amiga.IDCMP_NEWSIZE)
    win = _amiga.new_object_multi("window.class", [
        ("WA_ScreenTitle",  "Python File Manager v2 (ReAction)"),
        ("WA_Title",        f"{panes['left'].path}  |  {panes['right'].path}"),
        ("WA_Activate",     True),
        ("WA_DepthGadget",  True),
        ("WA_DragBar",      True),
        ("WA_CloseGadget",  True),
        ("WA_SizeGadget",   True),
        ("WA_IDCMP",        idcmp),
        ("WA_InnerWidth",   700),
        ("WA_InnerHeight",  400),
        ("WA_MinWidth",     400),
        ("WA_MinHeight",    250),
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

    # Handles indexed by side for GADGETUP dispatch on the listbrowser.
    lb_by_id  = {ID_LB_LEFT: ("left",  left_lb,  left_list_slot),
                 ID_LB_RIGHT: ("right", right_lb, right_list_slot)}

    def _current_pane():
        return panes[panes["focused"]]

    def _other_pane():
        return panes["right" if panes["focused"] == "left" else "left"]

    def _current_lb_info():
        side = panes["focused"]
        return (left_lb, left_list_slot) if side == "left" \
               else (right_lb, right_list_slot)

    # LISTBROWSER_Selected — not yet in TAG_TABLE. Raw value from
    # gadgets/listbrowser.h: LISTBROWSER_Dummy(0x85003000) + 4.
    _LISTBROWSER_SELECTED = 0x85003004

    def _get_selected_row_index(lb_handle):
        """Query the currently selected row index via GetAttr.
        Returns -1 if nothing selected."""
        idx = _amiga.get_attr(lb_handle, _LISTBROWSER_SELECTED)
        # Normalise: unsigned ~0 (all bits set) becomes 0xffffffff
        return -1 if idx == 0xffffffff else int(idx)

    def _selected_entry():
        pane = _current_pane()
        lb, _slot = _current_lb_info()
        idx = _get_selected_row_index(lb)
        if 0 <= idx < len(pane.entries):
            return pane.entries[idx]
        return None

    def _do_copy():
        pane = _current_pane()
        dst  = _other_pane()
        e = _selected_entry()
        if not e:
            print("copy: nothing selected", flush=True); return
        name, is_dir, _sz, _mt = e
        if is_dir or name == "..":
            print(f"copy: skipping directory-like {name!r}", flush=True); return
        try:
            data = pane.read_file(name)
            dst.write_file(name, data)
            print(f"copy: {len(data)}b -> {dst.path}/{name}", flush=True)
            _refresh_lb(dst,
                         right_lb if panes["focused"] == "left" else left_lb,
                         right_list_slot if panes["focused"] == "left" else left_list_slot,
                         intuiwin)
        except Exception as e:
            print(f"copy failed: {type(e).__name__}: {e}", flush=True)

    def _do_set_path():
        pane = _current_pane()
        new = _prompt("Set pane path",
                      "path (DH1: or s3:// or s3://bucket)",
                      pane.path, 200)
        if not new or new == pane.path:
            return
        try:
            new_pane = _fm.make_pane(new.strip(), r, r)
            panes[panes["focused"]] = new_pane
            side = panes["focused"]
            lb   = left_lb  if side == "left" else right_lb
            slot = left_list_slot if side == "left" else right_list_slot
            _refresh_lb(new_pane, lb, slot, intuiwin)
            print(f"set: {side} pane -> {new_pane.path}", flush=True)
        except Exception as e:
            print(f"set failed: {type(e).__name__}: {e}", flush=True)

    def _do_mkbucket():
        pane = _current_pane()
        if not pane.path.startswith("s3:"):
            print("mkbucket: focused pane isn't S3", flush=True); return
        # Only meaningful when pane is on `s3://` (bucket list level).
        # If it's inside a bucket, still allow creating a top-level
        # bucket — S3 buckets are flat.
        name = _prompt("Make S3 bucket",
                       "bucket name (lowercase, no /)", "", 63)
        if not name or not name.strip():
            return
        try:
            client = _fm._s3_client_from_env()
            client.make_bucket(name.strip())
            print(f"mkbucket: created {name!r}", flush=True)
            # If the pane is on s3://, refresh it to show new bucket.
            if pane.path.rstrip("/") in ("s3:", "s3://"):
                pane.refresh()
                side = panes["focused"]
                lb   = left_lb  if side == "left" else right_lb
                slot = left_list_slot if side == "left" else right_list_slot
                _refresh_lb(pane, lb, slot, intuiwin)
        except Exception as e:
            print(f"mkbucket failed: {type(e).__name__}: {e}", flush=True)

    def _do_refresh():
        panes["left"].refresh()
        panes["right"].refresh()
        _refresh_lb(panes["left"],  left_lb,  left_list_slot,  intuiwin)
        _refresh_lb(panes["right"], right_lb, right_list_slot, intuiwin)
        print("refreshed", flush=True)

    # LISTBROWSER_RelEvent (GetAttr) returns the click type:
    #   LBRE_NORMAL = 1     — single click / selection change
    #   LBRE_DOUBLECLICK = 16
    #   LBRE_HIDECHILDREN=2, LBRE_SHOWCHILDREN=4, etc. — hierarchy
    # We only care about NORMAL vs DOUBLECLICK. This is more reliable
    # than tracking time diffs ourselves — listbrowser has already
    # decided the classification.
    _LISTBROWSER_RelEvent = 0x85003025
    LBRE_NORMAL      = 1
    LBRE_DOUBLECLICK = 16

    def _handle_lb_click(gid):
        """Listbrowser row-click — mark that pane as focused, query
        which row is selected, and check RelEvent for single vs
        double-click.

        Single-click → select + report; double-click on a directory
        row → descend (or ascend on `..`). Row index isn't in the
        GADGETUP code; must GetAttr LISTBROWSER_Selected."""
        if gid not in lb_by_id:
            return
        side, lb, _slot = lb_by_id[gid]
        panes["focused"] = side
        pane = _current_pane()
        row = _get_selected_row_index(lb)
        rel = _amiga.get_attr(lb, _LISTBROWSER_RelEvent)
        if not (0 <= row < len(pane.entries)):
            print(f"select: {side} (no row) rel={rel}", flush=True)
            return
        entry = pane.entries[row]
        name, is_dir, _sz, _mt = entry
        is_double = (rel == LBRE_DOUBLECLICK)

        if is_double and is_dir:
            # Descend (or ascend on ".."). Can't use pane.enter_selected()
            # because it reads self.list.selected from the amiga.ui
            # ListPanel — our ReAction listbrowser doesn't populate
            # that. Set the path directly and refresh.
            try:
                if name == "..":
                    pane.go_parent()
                else:
                    # Build the new path. For S3Pane, path is
                    # s3://[bucket[/prefix]]. For LocalPane it's a
                    # local path. Both handle "join name" the same way
                    # via string concat, but S3 needs the s3:// prefix
                    # preserved. Sync sync — sync the selection index
                    # into the pane's ListPanel first, then call
                    # enter_selected which uses that.
                    pane.list.selected = row
                    pane.enter_selected()
                lb_h  = left_lb  if side == "left" else right_lb
                slot  = left_list_slot if side == "left" else right_list_slot
                _refresh_lb(pane, lb_h, slot, intuiwin)
                print(f"descend: {side} -> {pane.path}", flush=True)
            except Exception as exc:
                print(f"descend failed: {type(exc).__name__}: {exc}",
                      flush=True)
        else:
            print(f"select: {side}[{row}] = {name!r}"
                  f"{' (dir)' if is_dir else ''}", flush=True)

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
                # WM_RETHINK = 0x570006 (from classes/window.h).
                _amiga.do_method(win, 0x570006)
                continue
            if cls == _amiga.IDCMP_GADGETUP:
                if code == ID_BTN_SET:      _do_set_path()
                elif code == ID_BTN_COPY:   _do_copy()
                elif code == ID_BTN_REFRESH: _do_refresh()
                elif code == ID_BTN_MKB:    _do_mkbucket()
                elif code == ID_BTN_QUIT:   break
                elif code in lb_by_id:      _handle_lb_click(code)
    finally:
        _amiga.do_method(win, _amiga.WM_CLOSE)
        _amiga.dispose_object(win)
        if left_list_slot[0]:  _amiga.lb_free_list(left_list_slot[0])
        if right_list_slot[0]: _amiga.lb_free_list(right_list_slot[0])
    print("fileman2: bye", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
