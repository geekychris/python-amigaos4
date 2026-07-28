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

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga

# Reuse pane model from fileman v1.
sys.path.insert(0, "DH1:pytests/examples")
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
ID_BTN_DELETE  = 105
ID_BTN_REFRESH = 102
ID_BTN_MKB     = 103
ID_BTN_CONFIG  = 106
ID_BTN_QUIT    = 104


# ---------------------------------------------------------------- pane wiring

def _rows_from_pane(pane):
    """Convert a Pane's entries into listbrowser rows: (name, size|<DIR>)."""
    try:
        entries = pane.entries
        print(f"  _rows_from_pane: pane.path={pane.path} "
              f"nentries={len(entries)}", flush=True)
    except Exception as ex:
        print(f"  _rows_from_pane: pane.entries FAILED "
              f"{type(ex).__name__}: {ex}", flush=True)
        return []
    rows = []
    for name, is_dir, size, _mtime in entries:
        kind = "<DIR>" if is_dir else str(size)
        rows.append([name, kind])
    return rows


def _refresh_lb(pane, lb_handle, list_slot, win_handle=0):
    """Rebuild the listbrowser rows from the pane's current entries.

    win_handle is passed to set_attrs so the listbrowser knows which
    window to redraw itself in — 0 works pre-open, real handle after
    WM_OPEN."""
    print(f"  _refresh_lb: pane.path={pane.path} lb=0x{lb_handle:x} "
          f"win=0x{win_handle:x} old_list={list_slot[0]}", flush=True)
    rows = _rows_from_pane(pane)
    print(f"  _refresh_lb: nrows={len(rows)} first={rows[0] if rows else None}",
          flush=True)
    new_list = _amiga.lb_make_list(rows)
    print(f"  _refresh_lb: new_list={new_list}", flush=True)
    # Detach old list before freeing to avoid a redraw on freed nodes.
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": 0}, win_handle)
    print(f"  _refresh_lb: detached old labels", flush=True)
    if list_slot[0]:
        try:
            _amiga.lb_free_list(list_slot[0])
            print(f"  _refresh_lb: freed old list", flush=True)
        except Exception as ex:
            print(f"  _refresh_lb: free failed {type(ex).__name__}: {ex}",
                  flush=True)
    list_slot[0] = new_list
    _amiga.set_attrs(lb_handle, {"LISTBROWSER_Labels": new_list},
                    win_handle)
    print(f"  _refresh_lb: attached new labels — done", flush=True)


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


def _multi_prompt(title, fields, ok="OK", cancel="Cancel"):
    """Show a multi-field dialog. `fields` is a list of
    (label, default, maxlen) tuples. Returns dict of label->value
    on OK, None on Cancel."""
    if not hasattr(_amiga, "open_dialog"):
        return None
    h = _amiga.open_dialog(title=title, fields=fields,
                            ok_label=ok, cancel_label=cancel,
                            left=180, top=100)
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


# ---------------------------------------------------------------- config
# S3 config persistence. Stores to ENVARC: (survives reboot) and ENV:
# (immediate; picked up by any new subprocess or by re-reading os.environ).
# Format is one KEY=VALUE per line — compatible with `getenv KEY` and
# the s3-env-local launcher script (which does `setenv KEY VALUE`).

S3_CONFIG_KEYS = ("S3_ENDPOINT", "S3_ACCESS", "S3_SECRET", "S3_INSECURE",
                  "S3_TIME_SKEW")

# Multi-profile store. One JSON file with {name: {...S3_ vars...}}.
# ENVARC: survives reboot, ENV: is a session copy the s3 CLI shells see.
S3_PROFILES_FILE = "ENVARC:s3-profiles.json"


def _profiles_load():
    """Read the profiles file; return dict {name: {k: v}}.
    On first run (empty file) seed one profile from the current env
    vars — usually populated by s3-env-local — so the user has
    something to Edit / Activate immediately."""
    import json
    try:
        with open(S3_PROFILES_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, dict) and data:
            return data
    except (FileNotFoundError, OSError, ValueError):
        pass
    # Seed if we have live creds in ENV: (typical from s3-env-local)
    ep = os.environ.get("S3_ENDPOINT", "")
    if ep:
        seed = {k: os.environ.get(k, "") for k in S3_CONFIG_KEYS}
        name = "minio-local" if "10.0.2.2" in ep else "default"
        return {name: seed}
    return {}


def _profiles_save(profiles):
    """Persist the full profiles dict."""
    import json
    with open(S3_PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


def _s3_config_load():
    """Current env values (the active profile)."""
    return {k: os.environ.get(k, "") for k in S3_CONFIG_KEYS}


def _s3_config_activate(cfg):
    """Push a profile's values into ENV: + ENVARC: so the CLI and next
    boot see it. OS4 setenv writes to ENV:; we copy to ENVARC: too."""
    for k in S3_CONFIG_KEYS:
        v = str(cfg.get(k, "")).replace('"', '\\"')
        os.environ[k] = str(cfg.get(k, ""))
        os.system(f'setenv {k} "{v}"')
        os.system(f'copy ENV:{k} ENVARC:{k} QUIET')


# ---------------------------------------------------------------- main

def main():
    left_spec  = os.environ.get("FILEMAN2_LEFT",  "SYS:")
    right_spec = os.environ.get("FILEMAN2_RIGHT", "DH1:")

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

    # Column info — SEPARATE array per listbrowser. Sharing one
    # ColumnInfo pointer across two listbrowsers means both mutate the
    # same widths (via AutoFit / drag / etc) and columns end up in
    # inconsistent states.
    # CIF_WEIGHTED is the default (flags=0). Values are RELATIVE
    # weights, not pixel widths. Keep them small.
    cols_left  = _amiga.lb_make_columns([("Name", 4), ("Size", 1)])
    cols_right = _amiga.lb_make_columns([("Name", 4), ("Size", 1)])

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
    # GA_RelVerify is what tells the gadget to emit GADGETUP on mouse
    # release — WITHOUT this, the listbrowser draws a selection highlight
    # but never fires a click event that WM_HANDLEINPUT can dispatch.
    # (SDK twocolumn.c sets this on every listbrowser.)
    # Build initial label lists BEFORE creating the listbrowsers, and
    # pass them via LISTBROWSER_Labels at creation. Confirmed by
    # lb_minimal test: passing Labels only via later set_attrs leaves
    # the click-dispatch subsystem uninitialised so GADGETUP never
    # fires. Refreshing via set_attrs later still works fine.
    left_list_slot[0]  = _amiga.lb_make_list(_rows_from_pane(panes["left"]))
    right_list_slot[0] = _amiga.lb_make_list(_rows_from_pane(panes["right"]))

    # AutoFit off — it re-sizes columns based on content, which makes
    # the two panes render at different widths when their initial
    # contents differ (screenshot: right pane clipped "hello" → "hell").
    # Explicit weights + separate ColumnInfo per listbrowser keeps
    # them consistent.
    _lb_common = [
        ("GA_RelVerify",            True),
        (_LISTBROWSER_AutoFit,      False),
        (_LISTBROWSER_ShowSelected, True),
        (_LISTBROWSER_ColumnTitles, False),
        # MultiSelect on: user can Shift/Ctrl-click to add rows to
        # the selection. Enumerate the full set with
        # _amiga.lb_selected_indices(list_slot[0]).
        (_LISTBROWSER_MultiSelect,  True),
    ]
    left_lb  = _amiga.new_object_multi("listbrowser.gadget",
        [("GA_ID", ID_LB_LEFT),
         ("LISTBROWSER_ColumnInfo", cols_left),
         ("LISTBROWSER_Labels", left_list_slot[0])] + _lb_common)
    right_lb = _amiga.new_object_multi("listbrowser.gadget",
        [("GA_ID", ID_LB_RIGHT),
         ("LISTBROWSER_ColumnInfo", cols_right),
         ("LISTBROWSER_Labels", right_list_slot[0])] + _lb_common)

    # Buttons — ID_BTN_* values feed the GADGETUP dispatch below.
    def _mkbtn(bid, label):
        return _amiga.new_object("button.gadget",
                                  {"GA_ID": bid, "GA_Text": label,
                                   "GA_RelVerify": True})

    b_set     = _mkbtn(ID_BTN_SET,     "Source")
    b_copy    = _mkbtn(ID_BTN_COPY,    "Copy")
    b_delete  = _mkbtn(ID_BTN_DELETE,  "Delete")
    b_refresh = _mkbtn(ID_BTN_REFRESH, "Refresh")
    b_mkb     = _mkbtn(ID_BTN_MKB,     "New Bucket")
    b_config  = _mkbtn(ID_BTN_CONFIG,  "S3 Servers")
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
        ("LAYOUT_AddChild",    b_delete),
        ("LAYOUT_AddChild",    b_refresh),
        ("LAYOUT_AddChild",    b_mkb),
        ("LAYOUT_AddChild",    b_config),
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

    # NOTE: don't pass WA_IDCMP. window.class auto-derives the union of
    # IDCMP flags every child gadget needs (listbrowser wants MOUSEBUTTONS
    # / MOUSEMOVE / INTUITICKS for click+drag). Passing a fixed set here
    # restricts the port and blocks gadget dispatch — SDK examples like
    # twocolumn.c omit WA_IDCMP entirely.
    win = _amiga.new_object_multi("window.class", [
        ("WA_ScreenTitle",  "Python File Manager v2 (ReAction)"),
        ("WA_Title",        f"{panes['left'].path}  |  {panes['right'].path}"),
        ("WA_Activate",     True),
        ("WA_DepthGadget",  True),
        ("WA_DragBar",      True),
        ("WA_CloseGadget",  True),
        ("WA_SizeGadget",   True),
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

    class _Busy:
        """Context manager that shows the busy pointer on the main
        window for the duration of the block. Silently no-ops on old
        pythons without _amiga.set_busy."""
        def __enter__(self):
            if hasattr(_amiga, "set_busy") and intuiwin:
                try: _amiga.set_busy(intuiwin, True)
                except Exception: pass
            return self
        def __exit__(self, *exc):
            if hasattr(_amiga, "set_busy") and intuiwin:
                try: _amiga.set_busy(intuiwin, False)
                except Exception: pass

    def _current_lb_slot():
        """Return the (lb_handle, list_slot) for the focused pane."""
        side = panes["focused"]
        return ((left_lb, left_list_slot) if side == "left"
                else (right_lb, right_list_slot))

    def _selected_indices():
        """All rows currently selected in the focused pane's
        listbrowser. Empty list if none. Uses MultiSelect-aware
        node walk; falls back to LISTBROWSER_Selected for the
        no-multi-select case."""
        _, slot = _current_lb_slot()
        if not slot[0]:
            return []
        try:
            idxs = _amiga.lb_selected_indices(slot[0])
            if idxs:
                return idxs
        except Exception:
            pass
        # Fallback: single-select last-clicked
        lb, _ = _current_lb_slot()
        r = _get_selected_row_index(lb)
        return [r] if r >= 0 else []

    def _do_copy():
        pane = _current_pane()
        dst  = _other_pane()
        idxs = _selected_indices()
        if not idxs:
            print("copy: nothing selected", flush=True); return
        # Filter to files (skip dirs and '..'), report skipped
        to_copy = []
        for i in idxs:
            if 0 <= i < len(pane.entries):
                name, is_dir, _sz, _mt = pane.entries[i]
                if is_dir or name == "..":
                    print(f"copy: skipping {name!r} (dir)", flush=True)
                else:
                    to_copy.append(name)
        if not to_copy:
            print("copy: nothing to copy (all dirs)", flush=True); return
        print(f"== _do_copy: {len(to_copy)} file(s) "
              f"from {pane.path} to {dst.path}", flush=True)
        dst_lb   = right_lb if panes["focused"] == "left" else left_lb
        dst_slot = (right_list_slot
                    if panes["focused"] == "left" else left_list_slot)
        ok = 0
        with _Busy():
            for name in to_copy:
                try:
                    print(f"  copy: read {pane.path}/{name}", flush=True)
                    data = pane.read_file(name)
                    print(f"  copy: got {len(data)}b, writing to "
                          f"{dst.path}/{name}", flush=True)
                    dst.write_file(name, data)
                    ok += 1
                    print(f"  copy: wrote {name} OK", flush=True)
                except Exception as e:
                    import traceback
                    print(f"  copy: FAILED {name} — "
                          f"{type(e).__name__}: {e}\n"
                          f"{traceback.format_exc()}", flush=True)
            # Refresh dst ONCE at the end — otherwise we'd re-list S3 on
            # every file which is both slow and hits the openssl-subprocess
            # instability.
            print(f"== _do_copy: {ok}/{len(to_copy)} succeeded, "
                  f"refreshing dst", flush=True)
            try:
                dst.refresh()
                _refresh_lb(dst, dst_lb, dst_slot, intuiwin)
            except Exception as e:
                import traceback
                print(f"== _do_copy: dst refresh FAILED — "
                      f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                      flush=True)
        print(f"== _do_copy: done ({ok} files copied)", flush=True)

    def _enum_sources():
        """Build the picker's source list. Returns list of
        (display_name, target_path) tuples. Local volumes first, then
        S3 buckets on the currently-active profile."""
        sources = []
        # Local volumes — os.listdir('/') on OS4 returns all mounted
        # volumes and assigns as top-level entries.
        try:
            for name in sorted(os.listdir("/")):
                if not name:
                    continue
                path = name + ":" if not name.endswith(":") else name
                sources.append((f"Local: {path}", path))
        except Exception as e:
            print(f"enum_sources: listdir(/) failed: {e}", flush=True)
        # S3 buckets on the ACTIVE profile.
        try:
            active_ep = os.environ.get("S3_ENDPOINT", "")
            if active_ep:
                # Figure out the active profile's NAME (for the label)
                profiles = _profiles_load()
                active_name = "?"
                for n, cfg in profiles.items():
                    if cfg.get("S3_ENDPOINT") == active_ep:
                        active_name = n; break
                # Always include the bucket-list root.
                sources.append((f"S3 [{active_name}]: (bucket list)", "s3://"))
                client = _fm._s3_client_from_env()
                with _Busy():
                    for b in client.list_buckets():
                        sources.append(
                            (f"S3 [{active_name}]: {b['name']}",
                             f"s3://{b['name']}"))
        except Exception as e:
            import traceback
            print(f"enum_sources: S3 list failed: {e}\n"
                  f"{traceback.format_exc()}", flush=True)
        return sources

    # Button IDs for the source picker (scoped to that window).
    _SP_LB     = 400
    _SP_OPEN   = 401
    _SP_MANUAL = 402
    _SP_CLOSE  = 403

    def _pick_source():
        """Open a picker with all available data sources for the
        focused pane. Double-click a row OR Open button: switch the
        pane. Manual button: fall back to typing a path. Close:
        cancel."""
        sources = _enum_sources()
        if not sources:
            # Fall back to plain prompt if we couldn't enumerate.
            return _do_set_path_prompt()
        rows = [[label, path] for label, path in sources]
        cols = _amiga.lb_make_columns([("Source", 3), ("Path", 2)])
        list_slot = [_amiga.lb_make_list(rows)]

        lb = _amiga.new_object_multi("listbrowser.gadget", [
            ("GA_ID", _SP_LB),
            ("GA_RelVerify",            True),
            ("LISTBROWSER_ColumnInfo",  cols),
            ("LISTBROWSER_Labels",      list_slot[0]),
            (0x85003010, False),   # AutoFit
            (0x85003012, True),    # ShowSelected
            (0x85003011, False),   # ColumnTitles
        ])

        def _mkb(bid, label):
            return _amiga.new_object("button.gadget",
                {"GA_ID": bid, "GA_Text": label, "GA_RelVerify": True})

        b_open   = _mkb(_SP_OPEN,   "Open")
        b_manual = _mkb(_SP_MANUAL, "Custom path...")
        b_close  = _mkb(_SP_CLOSE,  "Cancel")

        _CHILD_WH = 0x85007106
        btn_row = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 0),
            ("LAYOUT_SpaceInner",  True),
            ("LAYOUT_EvenSize",    True),
            ("LAYOUT_AddChild",    b_open),
            ("LAYOUT_AddChild",    b_manual),
            ("LAYOUT_AddChild",    b_close),
        ])
        root = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 1),
            ("LAYOUT_SpaceInner",  True),
            ("LAYOUT_AddChild",    lb),
            ("LAYOUT_AddChild",    btn_row),
            (_CHILD_WH,            0),
        ])
        win = _amiga.new_object_multi("window.class", [
            ("WA_Title",       f"Choose source for {panes['focused']} pane"),
            ("WA_ScreenTitle", "fileman2 source picker"),
            ("WA_Activate",    True),
            ("WA_DragBar",     True),
            ("WA_CloseGadget", True),
            ("WA_SizeGadget",  True),
            ("WA_InnerWidth",  480),
            ("WA_InnerHeight", 240),
            ("WINDOW_Position", _amiga.WPOS_CENTERMOUSE),
            ("WINDOW_Layout",  root),
        ])
        if _amiga.do_method(win, _amiga.WM_OPEN) == 0:
            _amiga.dispose_object(win)
            return None
        piw = _amiga.get_attr(win, 0x81021001)

        picked = [None]  # closure return

        def _selected_source():
            idx = _amiga.get_attr(lb, 0x85003004)
            if idx == 0xffffffff: return None
            if 0 <= idx < len(sources): return sources[idx][1]
            return None

        WMHI_CLASSMASK  = 0xFFFF0000
        WMHI_GADGETMASK = 0x0000FFFF
        WMHI_CLOSE      = 1  << 16
        WMHI_GADGETUP   = 2  << 16
        stop = False
        _LISTBROWSER_RelEvent = 0x85003025
        LBRE_DOUBLECLICK      = 16
        try:
            while not stop:
                drained = False
                while True:
                    r = _amiga.wm_handleinput(win)
                    if r is None: break
                    drained = True
                    result, _code = r
                    cls, gid = (result & WMHI_CLASSMASK,
                                result & WMHI_GADGETMASK)
                    if cls == WMHI_CLOSE:
                        stop = True; break
                    if cls != WMHI_GADGETUP: continue
                    if gid == _SP_CLOSE:
                        stop = True; break
                    if gid == _SP_MANUAL:
                        p = _prompt("Custom path", "Path",
                                    _current_pane().path, 200)
                        if p:
                            picked[0] = p.strip()
                        stop = True; break
                    if gid == _SP_OPEN:
                        picked[0] = _selected_source()
                        if picked[0]:
                            stop = True; break
                    if gid == _SP_LB:
                        # Double-click a row = immediate pick
                        rel = _amiga.get_attr(lb, _LISTBROWSER_RelEvent)
                        if rel == LBRE_DOUBLECLICK:
                            picked[0] = _selected_source()
                            if picked[0]:
                                stop = True; break
                if not drained:
                    time.sleep(0.03)
        finally:
            _amiga.do_method(win, _amiga.WM_CLOSE)
            _amiga.dispose_object(win)
            if list_slot[0]:
                try: _amiga.lb_free_list(list_slot[0])
                except Exception: pass
        return picked[0]

    def _do_set_path_prompt():
        return _prompt("Set pane path",
                       "path (DH1: or s3:// or s3://bucket)",
                       _current_pane().path, 200)

    def _do_set_path():
        try:
            target = _pick_source()
            if not target:
                print("set: cancelled", flush=True); return
            pane = _current_pane()
            if target == pane.path:
                print("set: no change", flush=True); return
            new_pane = _fm.make_pane(target, r, r)
            panes[panes["focused"]] = new_pane
            side = panes["focused"]
            lb   = left_lb  if side == "left" else right_lb
            slot = left_list_slot if side == "left" else right_list_slot
            _refresh_lb(new_pane, lb, slot, intuiwin)
            print(f"set: {side} pane -> {new_pane.path}", flush=True)
        except Exception as e:
            import traceback
            print(f"set failed: {type(e).__name__}: {e}\n"
                  f"{traceback.format_exc()}", flush=True)

    def _do_delete():
        try:
            pane = _current_pane()
            idxs = _selected_indices()
            if not idxs:
                print("delete: nothing selected", flush=True); return
            to_del = []
            for i in idxs:
                if 0 <= i < len(pane.entries):
                    name, is_dir, _, _ = pane.entries[i]
                    if name == "..":
                        continue
                    if is_dir:
                        print(f"delete: skipping {name!r} (dir)", flush=True)
                        continue
                    to_del.append(name)
            if not to_del:
                print("delete: nothing to delete (all dirs)", flush=True)
                return
            print(f"== _do_delete: {len(to_del)} file(s) from {pane.path}",
                  flush=True)
            ok = 0
            with _Busy():
                for name in to_del:
                    try:
                        print(f"  del: {pane.path}/{name}", flush=True)
                        pane.delete_entry(name)
                        ok += 1
                    except Exception as ex:
                        import traceback
                        print(f"  del: FAILED {name} — "
                              f"{type(ex).__name__}: {ex}\n"
                              f"{traceback.format_exc()}", flush=True)
                pane.refresh()
                side = panes["focused"]
                lb   = left_lb  if side == "left" else right_lb
                slot = left_list_slot if side == "left" else right_list_slot
                _refresh_lb(pane, lb, slot, intuiwin)
            print(f"== _do_delete: {ok}/{len(to_del)} succeeded", flush=True)
        except Exception as ex:
            import traceback
            print(f"== _do_delete: FAILED {type(ex).__name__}: {ex}\n"
                  f"{traceback.format_exc()}", flush=True)

    def _edit_profile_fields(name, defaults):
        """Open a field-edit dialog for one profile. Returns the new
        cfg dict on Save, or None on Cancel."""
        r = _multi_prompt(
            f"S3 profile: {name}",
            [("Endpoint",    defaults.get("S3_ENDPOINT", ""),   80),
             ("Access Key",  defaults.get("S3_ACCESS", ""),     80),
             ("Secret Key",  defaults.get("S3_SECRET", ""),     80),
             ("Insecure TLS", defaults.get("S3_INSECURE", ""),   8),
             ("Time Skew",   defaults.get("S3_TIME_SKEW", ""), 12)],
            ok="Save", cancel="Cancel")
        if r is None:
            return None
        return {
            "S3_ENDPOINT":  r.get("Endpoint", ""),
            "S3_ACCESS":    r.get("Access Key", ""),
            "S3_SECRET":    r.get("Secret Key", ""),
            "S3_INSECURE":  r.get("Insecure TLS", ""),
            "S3_TIME_SKEW": r.get("Time Skew", ""),
        }

    def _do_config():
        """Open the profile picker window: a listbrowser of profile
        names + [New, Edit, Delete, Activate, Close] buttons."""
        try:
            _open_profile_picker()
        except Exception as ex:
            import traceback
            print(f"== _do_config: FAILED {type(ex).__name__}: {ex}\n"
                  f"{traceback.format_exc()}", flush=True)

    # Button IDs for the picker window (only meaningful inside its loop).
    _PB_NEW      = 300
    _PB_EDIT     = 301
    _PB_DELETE   = 302
    _PB_ACTIVATE = 303
    _PB_CLOSE    = 304
    _PB_LB       = 305

    def _open_profile_picker():
        profiles = _profiles_load()
        list_slot = [None]

        def _rebuild_rows():
            active = os.environ.get("S3_ENDPOINT", "")
            rows = []
            for n in sorted(profiles.keys()):
                marker = "*" if profiles[n].get("S3_ENDPOINT") == active else " "
                ep = profiles[n].get("S3_ENDPOINT", "")
                rows.append([f"{marker} {n}", ep])
            return rows

        cols = _amiga.lb_make_columns([("Profile", 3), ("Endpoint", 5)])
        list_slot[0] = _amiga.lb_make_list(_rebuild_rows())

        lb = _amiga.new_object_multi("listbrowser.gadget", [
            ("GA_ID", _PB_LB),
            ("GA_RelVerify",            True),
            ("LISTBROWSER_ColumnInfo",  cols),
            ("LISTBROWSER_Labels",      list_slot[0]),
            (0x85003010, False),   # AutoFit
            (0x85003012, True),    # ShowSelected
            (0x85003011, False),   # ColumnTitles
        ])

        def _mkb(bid, label):
            return _amiga.new_object("button.gadget",
                {"GA_ID": bid, "GA_Text": label, "GA_RelVerify": True})

        b_new    = _mkb(_PB_NEW,      "New")
        b_edit   = _mkb(_PB_EDIT,     "Edit")
        b_del    = _mkb(_PB_DELETE,   "Delete")
        b_act    = _mkb(_PB_ACTIVATE, "Activate")
        b_close  = _mkb(_PB_CLOSE,    "Close")

        _CHILD_WH = 0x85007106
        btn_row = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 0),       # HORIZ
            ("LAYOUT_SpaceInner",  True),
            ("LAYOUT_EvenSize",    True),
            ("LAYOUT_AddChild",    b_new),
            ("LAYOUT_AddChild",    b_edit),
            ("LAYOUT_AddChild",    b_del),
            ("LAYOUT_AddChild",    b_act),
            ("LAYOUT_AddChild",    b_close),
        ])
        root = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 1),       # VERT
            ("LAYOUT_SpaceInner",  True),
            ("LAYOUT_AddChild",    lb),
            ("LAYOUT_AddChild",    btn_row),
            (_CHILD_WH,            0),
        ])
        win = _amiga.new_object_multi("window.class", [
            ("WA_Title",       "S3 Servers (each holds endpoint + credentials)"),
            ("WA_ScreenTitle", "S3 server / profile manager"),
            ("WA_Activate",    True),
            ("WA_DragBar",     True),
            ("WA_CloseGadget", True),
            ("WA_SizeGadget",  True),
            ("WA_InnerWidth",  460),
            ("WA_InnerHeight", 200),
            ("WINDOW_Position", _amiga.WPOS_CENTERMOUSE),
            ("WINDOW_Layout",  root),
        ])
        pw = _amiga.do_method(win, _amiga.WM_OPEN)
        if pw == 0:
            print("profile picker: WM_OPEN failed", flush=True)
            _amiga.dispose_object(win)
            return
        piw = _amiga.get_attr(win, 0x81021001)  # WINDOW_Window

        def _selected_name():
            idx = _amiga.get_attr(lb, 0x85003004)  # SELECTED
            if idx == 0xffffffff:
                return None
            names = sorted(profiles.keys())
            if 0 <= idx < len(names):
                return names[idx]
            return None

        def _refresh_lb_local():
            new_list = _amiga.lb_make_list(_rebuild_rows())
            _amiga.set_attrs(lb, {"LISTBROWSER_Labels": 0}, piw)
            if list_slot[0]:
                try: _amiga.lb_free_list(list_slot[0])
                except Exception: pass
            list_slot[0] = new_list
            _amiga.set_attrs(lb, {"LISTBROWSER_Labels": new_list}, piw)

        WMHI_CLASSMASK  = 0xFFFF0000
        WMHI_GADGETMASK = 0x0000FFFF
        WMHI_CLOSE      = 1  << 16
        WMHI_GADGETUP   = 2  << 16
        stop = False
        try:
            while not stop:
                drained = False
                while True:
                    r = _amiga.wm_handleinput(win)
                    if r is None: break
                    drained = True
                    result, _code = r
                    cls, gid = result & WMHI_CLASSMASK, result & WMHI_GADGETMASK
                    if cls == WMHI_CLOSE:
                        stop = True; break
                    if cls != WMHI_GADGETUP:
                        continue
                    if gid == _PB_CLOSE:
                        stop = True; break
                    if gid == _PB_NEW:
                        name = _prompt("New S3 server",
                                        "Server name (e.g. dev, prod)",
                                        default="", maxlen=64)
                        if not name or not name.strip(): continue
                        name = name.strip()
                        cur = _s3_config_load()
                        new = _edit_profile_fields(name, cur)
                        if new is None: continue
                        # Reject profiles with no endpoint — they hang
                        # every subsequent S3 call.
                        if not new.get("S3_ENDPOINT", "").strip():
                            print(f"profile: refusing {name!r} — "
                                  f"endpoint is required", flush=True)
                            continue
                        profiles[name] = new
                        _profiles_save(profiles)
                        _refresh_lb_local()
                        print(f"profile: added {name!r}", flush=True)
                    elif gid == _PB_EDIT:
                        name = _selected_name()
                        if not name:
                            print("profile: nothing selected", flush=True)
                            continue
                        new = _edit_profile_fields(name, profiles[name])
                        if new is None: continue
                        profiles[name] = new
                        _profiles_save(profiles)
                        _refresh_lb_local()
                        print(f"profile: edited {name!r}", flush=True)
                    elif gid == _PB_DELETE:
                        name = _selected_name()
                        if not name:
                            print("profile: nothing selected", flush=True)
                            continue
                        del profiles[name]
                        _profiles_save(profiles)
                        _refresh_lb_local()
                        print(f"profile: deleted {name!r}", flush=True)
                    elif gid == _PB_ACTIVATE:
                        name = _selected_name()
                        if not name:
                            print("profile: nothing selected", flush=True)
                            continue
                        cfg = profiles[name]
                        # Refuse to activate a profile with empty
                        # endpoint — leaves the app trying to resolve
                        # "" which hangs openssl subprocesses and
                        # wedges the UI.
                        if not cfg.get("S3_ENDPOINT", "").strip():
                            print(f"profile: refusing to activate {name!r} — "
                                  f"empty S3_ENDPOINT (Edit first to set it)",
                                  flush=True)
                            continue
                        _s3_config_activate(cfg)
                        for p in (panes["left"], panes["right"]):
                            if hasattr(p, "_client"):
                                p._client = None
                        _refresh_lb_local()
                        print(f"profile: activated {name!r}", flush=True)
                if not drained:
                    time.sleep(0.03)
        finally:
            _amiga.do_method(win, _amiga.WM_CLOSE)
            _amiga.dispose_object(win)
            if list_slot[0]:
                try: _amiga.lb_free_list(list_slot[0])
                except Exception: pass

    def _do_mkbucket():
        # Find the S3 pane — try focused first, then the other. Buckets
        # are top-level, so we don't require the pane to be on s3://
        # exactly; s3://something also lets us create alongside.
        try:
            focused = _current_pane()
            other   = _other_pane()
            s3_side = None
            if focused.path.startswith("s3:"):
                pane, s3_side = focused, panes["focused"]
            elif other.path.startswith("s3:"):
                pane = other
                s3_side = "right" if panes["focused"] == "left" else "left"
            else:
                print("mkbucket: no S3 pane open — set one to s3:// first",
                      flush=True)
                return
            name = _prompt("Make S3 bucket",
                           "bucket name (lowercase, no /)", "", 63)
            if not name or not name.strip():
                print("mkbucket: cancelled", flush=True); return
            name = name.strip()
            print(f"== _do_mkbucket: creating {name!r} on {pane.path}",
                  flush=True)
            with _Busy():
                client = _fm._s3_client_from_env()
                client.make_bucket(name)
                # Refresh the S3 pane if it's at the bucket-list level
                # (s3://) so the new bucket appears.
                if pane.path.rstrip("/") in ("s3:", "s3://"):
                    pane.refresh()
                    lb   = left_lb  if s3_side == "left" else right_lb
                    slot = (left_list_slot if s3_side == "left"
                            else right_list_slot)
                    _refresh_lb(pane, lb, slot, intuiwin)
            print(f"== _do_mkbucket: created {name!r} — done", flush=True)
        except Exception as e:
            import traceback
            print(f"== _do_mkbucket: FAILED {type(e).__name__}: {e}\n"
                  f"{traceback.format_exc()}", flush=True)

    def _do_refresh():
        with _Busy():
            print("== _do_refresh: LEFT pane.refresh()", flush=True)
            try:
                panes["left"].refresh()
                print(f"   left.refresh ok, entries="
                      f"{len(panes['left'].entries)}", flush=True)
            except Exception as ex:
                import traceback
                print(f"   left.refresh FAILED {type(ex).__name__}: {ex}\n"
                      f"{traceback.format_exc()}", flush=True)
            print("== _do_refresh: RIGHT pane.refresh()", flush=True)
            try:
                panes["right"].refresh()
                print(f"   right.refresh ok, entries="
                      f"{len(panes['right'].entries)}", flush=True)
            except Exception as ex:
                import traceback
                print(f"   right.refresh FAILED {type(ex).__name__}: {ex}\n"
                      f"{traceback.format_exc()}", flush=True)
            print("== _do_refresh: LEFT listbrowser rebuild", flush=True)
            _refresh_lb(panes["left"],  left_lb,  left_list_slot,  intuiwin)
            print("== _do_refresh: RIGHT listbrowser rebuild", flush=True)
            _refresh_lb(panes["right"], right_lb, right_list_slot, intuiwin)
            print("== _do_refresh: done", flush=True)

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
        nent = len(pane.entries)
        print(f"lb_click: side={side} lb=0x{lb:x} row={row} rel={rel} "
              f"nentries={nent} path={pane.path}", flush=True)
        if not (0 <= row < nent):
            print(f"  → no valid row (row={row} vs nent={nent})", flush=True)
            return
        entry = pane.entries[row]
        name, is_dir, _sz, _mt = entry
        is_double = (rel == LBRE_DOUBLECLICK)
        print(f"  → entry={name!r} is_dir={is_dir} is_double={is_double}",
              flush=True)

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

    # WMHI codes (from SDK classes/window.h).
    WMHI_CLASSMASK   = 0xFFFF0000
    WMHI_GADGETMASK  = 0x0000FFFF
    WMHI_CLOSEWINDOW = 1  << 16
    WMHI_GADGETUP    = 2  << 16
    WMHI_RAWKEY      = 11 << 16
    WMHI_NEWSIZE     = 3  << 16   # WM_HANDLEINPUT reports NEWSIZE too
    WMHI_VANILLAKEY  = 12 << 16

    stop = False
    try:
        while not stop:
            # window.class swallows all IDCMP into its internal queue.
            # Drain via WM_HANDLEINPUT — returns None when empty. We
            # loop until dry, then sleep briefly to yield CPU. Using
            # time.sleep instead of Wait() because our wait_message
            # would consume messages before WM_HANDLEINPUT can dispatch
            # them (they're mutually exclusive drain APIs).
            drained_any = False
            while True:
                r = _amiga.wm_handleinput(win)
                if r is None:
                    break
                drained_any = True
                result, code = r
                cls = result & WMHI_CLASSMASK
                gid = result & WMHI_GADGETMASK
                print(f"wmhi: cls=0x{cls:08x} gid={gid} code={code}",
                      flush=True)
                if cls == WMHI_CLOSEWINDOW:
                    stop = True
                    break
                if cls == WMHI_VANILLAKEY and code == 27:
                    stop = True
                    break
                if cls == WMHI_NEWSIZE:
                    _amiga.do_method(win, 0x570006)  # WM_RETHINK
                    continue
                if cls == WMHI_GADGETUP:
                    if   gid == ID_BTN_SET:     _do_set_path()
                    elif gid == ID_BTN_COPY:    _do_copy()
                    elif gid == ID_BTN_DELETE:  _do_delete()
                    elif gid == ID_BTN_REFRESH: _do_refresh()
                    elif gid == ID_BTN_MKB:     _do_mkbucket()
                    elif gid == ID_BTN_CONFIG:  _do_config()
                    elif gid == ID_BTN_QUIT:    stop = True; break
                    elif gid in lb_by_id:       _handle_lb_click(gid)
            if not drained_any:
                time.sleep(0.03)
    finally:
        _amiga.do_method(win, _amiga.WM_CLOSE)
        _amiga.dispose_object(win)
        if left_list_slot[0]:  _amiga.lb_free_list(left_list_slot[0])
        if right_list_slot[0]: _amiga.lb_free_list(right_list_slot[0])
    print("fileman2: bye", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
