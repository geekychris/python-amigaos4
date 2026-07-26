#!/usr/bin/env python3
"""fileman.py — dual-pane file manager for AmigaOS 4 in Python.

Two ListPanels side by side, each showing the contents of one
directory.  Bottom bar has buttons: Copy, Move, Delete, MkDir,
Rename, Refresh, Swap, Quit.  Above each panel: a path label +
an "Up" button + a "Root" button.

Click a filename to select it in that pane.  Double-click / press
Enter with a directory selected to descend into it.  All file ops
target the currently-focused pane (green highlight) and act on
the *other* pane's path as the destination for Copy / Move.

Backed by:
  * stdlib os / shutil for the actual FS ops (works on OS4 via newlib)
  * amiga.ui for the widget dispatch + composite dialogs
  * _amiga.open_dialog for confirm / prompt dialogs

Runs anywhere Python 3 runs; the OS4 build is where it really shines.
"""
import os
import shutil
import stat
import sys
import time

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga
from amiga.ui import (App, Button, Label, ListPanel, Rect,
                       PEN_FG, PEN_BG, PEN_HI, PEN_ACC)


# ---------------------------------------------------------------------------
# Panel model — one dir + its listing + selection state
# ---------------------------------------------------------------------------

class Pane:
    def __init__(self, path, list_rect, label_rect):
        self.path = os.path.abspath(path) if path else "/"
        # On OS4, os.path.abspath('DH1:') -> DH1:, which we prefer.
        self.list_rect = list_rect
        self.label_rect = label_rect
        self.entries = []       # list[(name, is_dir, size, mtime)]
        self.list = ListPanel(rect=list_rect, items=[], row_h=13,
                               on_pick=self._on_pick)
        self.list.selected = -1
        self._on_pick_callback = None
        self.refresh()

    def _on_pick(self, app, idx, item):
        # remember pane for global handlers
        app.state["focused"] = self
        if self._on_pick_callback:
            self._on_pick_callback(app, idx, item)

    def selected_entry(self):
        i = self.list.selected
        if 0 <= i < len(self.entries):
            return self.entries[i]
        return None

    def selected_name(self):
        e = self.selected_entry()
        return e[0] if e else None

    def selected_path(self):
        name = self.selected_name()
        if not name or name == "..":
            return None
        return _join(self.path, name)

    def refresh(self):
        try:
            names = sorted(os.listdir(self.path))
        except OSError as e:
            self.entries = []
            self.list.items = [f"<error: {e.__class__.__name__}: {e}>"]
            return
        self.entries = []
        # synthesize a ".." entry (except at root)
        if self.path and self.path not in ("/", "SYS:", "DH0:", "DH1:") \
                and not self.path.endswith(":"):
            self.entries.append(("..", True, 0, 0))
        for n in names:
            full = _join(self.path, n)
            try:
                st = os.stat(full)
                is_dir = stat.S_ISDIR(st.st_mode)
                self.entries.append((n, is_dir, st.st_size, st.st_mtime))
            except OSError:
                self.entries.append((n, False, 0, 0))
        self.list.items = [_format_row(e) for e in self.entries]
        self.list.selected = 0 if self.entries else -1
        self.list.top = 0

    def enter_selected(self):
        e = self.selected_entry()
        if not e:
            return False
        name, is_dir, _, _ = e
        if not is_dir:
            return False
        if name == "..":
            self.path = _parent_of(self.path)
        else:
            self.path = _join(self.path, name)
        self.refresh()
        return True

    def go_root(self):
        # Pick the volume of the current path (bit before the first ':')
        i = self.path.find(":")
        if i > 0:
            self.path = self.path[:i + 1]
        else:
            self.path = "/"
        self.refresh()

    def go_parent(self):
        self.path = _parent_of(self.path)
        self.refresh()


# ---------------------------------------------------------------------------
# Path helpers — AmigaDOS paths use `:` as volume separator, `/` for parent.
# ---------------------------------------------------------------------------

def _join(base, name):
    if not base or base.endswith((":", "/")):
        return base + name
    return base + "/" + name


def _parent_of(path):
    if not path or path.endswith(":"):
        return path      # can't go above a volume
    # Trim trailing slash
    if path.endswith("/"):
        path = path[:-1]
    if "/" in path:
        return path.rsplit("/", 1)[0] or "/"
    if ":" in path:
        return path.split(":", 1)[0] + ":"
    return path


def _format_row(e):
    name, is_dir, size, mtime = e
    kind = "<DIR>" if is_dir else f"{size:>9d}"
    stamp = time.strftime("%Y-%m-%d", time.localtime(mtime)) if mtime else "          "
    if len(name) > 20:
        name = name[:19] + "»"     # a lax indicator that would-be non-ASCII got mapped
    return f"{name:<20s} {kind} {stamp}"


# ---------------------------------------------------------------------------
# Confirm + prompt dialogs (thin wrappers around _amiga.open_dialog)
# ---------------------------------------------------------------------------

def prompt(title, label, default="", maxlen=250):
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
    return None if r is None else r.get(label, default)


def confirm(title, message):
    """A confirm is just a read-only prompt with pre-filled `y` — poor
    man's yes/no.  User leaves the buffer as `y` and hits OK, or clears
    it (or hits Cancel) to say no."""
    r = prompt(title, message + "  (leave 'y' + OK to confirm)", "y", 4)
    return r is not None and r.strip().lower().startswith("y")


# ---------------------------------------------------------------------------
# File operations
# ---------------------------------------------------------------------------

def op_copy(app):
    src = app.state["focused"].selected_path()
    if not src:
        _msg(app, "no source selected"); return
    dst_pane = _other(app)
    dst = _join(dst_pane.path, os.path.basename(src))
    if not confirm("Copy", f"copy {src} -> {dst}"):
        _msg(app, "cancelled"); return
    try:
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        _msg(app, f"copied to {dst}")
        dst_pane.refresh()
    except Exception as e:
        _msg(app, f"copy failed: {e}")


def op_move(app):
    src = app.state["focused"].selected_path()
    if not src:
        _msg(app, "no source"); return
    dst = _join(_other(app).path, os.path.basename(src))
    if not confirm("Move", f"move {src} -> {dst}"):
        _msg(app, "cancelled"); return
    try:
        shutil.move(src, dst)
        _msg(app, f"moved to {dst}")
        app.state["focused"].refresh()
        _other(app).refresh()
    except Exception as e:
        _msg(app, f"move failed: {e}")


def op_delete(app):
    src = app.state["focused"].selected_path()
    if not src:
        _msg(app, "no target"); return
    if not confirm("Delete", f"delete {src} ?"):
        _msg(app, "cancelled"); return
    try:
        if os.path.isdir(src):
            shutil.rmtree(src)
        else:
            os.remove(src)
        _msg(app, f"deleted {src}")
        app.state["focused"].refresh()
    except Exception as e:
        _msg(app, f"delete failed: {e}")


def op_mkdir(app):
    name = prompt("MkDir", "new-dir-name", "", 60)
    if not name or not name.strip():
        _msg(app, "cancelled"); return
    full = _join(app.state["focused"].path, name.strip())
    try:
        os.mkdir(full)
        _msg(app, f"created {full}")
        app.state["focused"].refresh()
    except Exception as e:
        _msg(app, f"mkdir failed: {e}")


def op_rename(app):
    src = app.state["focused"].selected_path()
    if not src:
        _msg(app, "no target"); return
    new_name = prompt("Rename",
                       f"new name for {os.path.basename(src)}",
                       os.path.basename(src), 100)
    if not new_name or not new_name.strip():
        _msg(app, "cancelled"); return
    dst = _join(os.path.dirname(src), new_name.strip())
    try:
        os.rename(src, dst)
        _msg(app, f"renamed -> {new_name}")
        app.state["focused"].refresh()
    except Exception as e:
        _msg(app, f"rename failed: {e}")


def op_refresh(app):
    for p in (app.state["left"], app.state["right"]):
        p.refresh()
    _msg(app, "refreshed")


def op_swap(app):
    l, r = app.state["left"], app.state["right"]
    l.path, r.path = r.path, l.path
    l.refresh(); r.refresh()
    _msg(app, "swapped")


def op_quit(app):
    app.stop()


# ---------------------------------------------------------------------------
# Layout + redraw
# ---------------------------------------------------------------------------

def _other(app):
    f = app.state["focused"]
    return app.state["right"] if f is app.state["left"] else app.state["left"]


def _msg(app, text):
    app.state["msg"] = f"{time.strftime('%H:%M:%S')} {text}"


def draw_header(app):
    l = app.state["left"]; r = app.state["right"]
    focus = app.state.get("focused")

    def _draw_pane_header(pane, x, y):
        marker = "*" if pane is focus else " "
        text = f"{marker} {pane.path}"
        if len(text) > 42:
            text = text[:42]
        app.text(x, y, text, PEN_ACC if pane is focus else PEN_FG)

    _draw_pane_header(l,   8, 20)
    _draw_pane_header(r, 408, 20)


def draw_status(app):
    app.fill(4, 388, 812, 404, PEN_BG)
    app.text(8, 400, app.state.get("msg", ""), PEN_HI)


def main():
    app = App(title="Python File Manager",
              w=820, h=440, left=40, top=30)

    left  = Pane("SYS:",
                  list_rect=Rect(8,   30, 400, 340),
                  label_rect=Rect(8,   16, 400,  30))
    right = Pane("DH1:",
                  list_rect=Rect(408, 30, 800, 340),
                  label_rect=Rect(408, 16, 800,  30))

    def on_pick_left(app, idx, item):
        app.state["focused"] = left
        # double-click behaviour approximated: if the same row was
        # already selected and it's a directory, descend into it.
        # (No real double-click event in IDCMP without more work.)
    def on_pick_right(app, idx, item):
        app.state["focused"] = right

    left._on_pick_callback  = on_pick_left
    right._on_pick_callback = on_pick_right

    app.state["left"]    = left
    app.state["right"]   = right
    app.state["focused"] = left
    app.state["msg"]     = "focus a pane by clicking, then use a button below"

    # Bottom bar
    W = 78
    y0, y1 = 350, 380
    def _btn(x, label, fn):
        return Button(Rect(x, y0, x + W, y1), label, on_click=fn)
    buttons = [
        _btn(  8, "Enter",   lambda a: a.state["focused"].enter_selected() or True),
        _btn( 92, "Up",      lambda a: a.state["focused"].go_parent()),
        _btn(176, "Root",    lambda a: a.state["focused"].go_root()),
        _btn(260, "Copy",    op_copy),
        _btn(344, "Move",    op_move),
        _btn(428, "Delete",  op_delete),
        _btn(512, "Rename",  op_rename),
        _btn(596, "MkDir",   op_mkdir),
        _btn(680, "Refresh", op_refresh),
        _btn(736, "Quit",    op_quit),
    ]

    app.widgets = [left.list, right.list, *buttons]

    def redraw(a):
        a.clear(PEN_BG)
        draw_header(a)
        a.draw_widgets()
        draw_status(a)

    def on_key(a, ch, code):
        if ch == "q":
            op_quit(a); return True
        # Tab-like: swap focus with 's'
        if ch == "s":
            a.state["focused"] = _other(a); return True
        if ch == "r":
            op_refresh(a); return True
        if ch == "\r" or code == 13:
            a.state["focused"].enter_selected(); return True
        return False

    app.redraw = redraw
    app.on_key = on_key
    app.run()


if __name__ == "__main__":
    main()
