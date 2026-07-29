#!/usr/bin/env python3
"""fileman.py — dual-pane file manager for AmigaOS 4 in Python.

Both panes can now be *either* a local filesystem directory *or* an
S3 (MinIO-compatible) prefix. Copy / Move / Delete / MkDir / Rename
work cross-storage: pick a file in the S3 pane, focus that pane, hit
Copy, and it's downloaded and written to the other pane's directory.

Startup:
  Left pane defaults to  SYS:
  Right pane defaults to DH1:

Configure S3 pane via env vars (set once at launch):
  S3_ENDPOINT    e.g. 10.0.2.2:9000 (local MinIO) or play.min.io
  S3_ACCESS      access key
  S3_SECRET      secret key
  S3_INSECURE    "1" to skip cert verify (needed for self-signed)

Then use the "Set" button on either pane to point it at:
  DH1:                        — local Amiga volume
  RAM:                        — RAM disk
  /Users/chris                — Unix-style local path
  s3://                       — S3 bucket list
  s3://mybucket               — top of a bucket
  s3://mybucket/photos/2026   — a "folder" inside a bucket

Backed by:
  * stdlib os / shutil for local FS
  * amiga.s3 for S3 (SigV4 signed HTTPS via amiga.https)
  * amiga.ui for the widget dispatch
  * _amiga.open_dialog for confirm / prompt dialogs
"""
import os
import shutil
import stat
import sys
import time

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga
from amiga.ui import (App, Button, Label, ListPanel, Rect,
                       PEN_FG, PEN_BG, PEN_HI, PEN_ACC)

# S3 support is optional — if the module isn't there, we still work
# as a plain local file manager.
try:
    from amiga import s3 as _s3
    _HAS_S3 = True
except ImportError:
    _s3 = None
    _HAS_S3 = False


# ---------------------------------------------------------------------------
# Base pane interface — every storage backend implements these
# ---------------------------------------------------------------------------

class BasePane:
    """A single pane worth of entries + selection state.

    Subclasses implement the storage-specific parts; the file ops in
    this module just call read_file / write_file / delete_entry etc.
    against the focused pane and the *other* pane, and copies fall
    out for free."""
    def __init__(self, path, list_rect, label_rect):
        self.path = path
        self.list_rect = list_rect
        self.label_rect = label_rect
        self.entries = []               # list of (name, is_dir, size, mtime)
        self.list = ListPanel(rect=list_rect, items=[], row_h=13,
                               on_pick=self._on_pick)
        self.list.selected = -1
        self._on_pick_callback = None
        self.refresh()

    # --- selection helpers, storage-agnostic ---
    def _on_pick(self, app, idx, item):
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

    # --- storage-specific, must be implemented by subclass ---
    def refresh(self):
        raise NotImplementedError

    def enter_selected(self):
        """Descend if the selection is a directory/prefix. Returns
        True on descent, False if it was a file."""
        raise NotImplementedError

    def go_parent(self):
        raise NotImplementedError

    def go_root(self):
        raise NotImplementedError

    def read_file(self, name) -> bytes:
        raise NotImplementedError

    def write_file(self, name, data: bytes):
        raise NotImplementedError

    def delete_entry(self, name):
        raise NotImplementedError

    def mkdir(self, name):
        raise NotImplementedError

    def rename(self, old, new):
        raise NotImplementedError

    def label(self) -> str:
        """Prefix + path for the status bar."""
        return self.path


# ---------------------------------------------------------------------------
# LocalPane — filesystem via os / shutil
# ---------------------------------------------------------------------------

def _join_local(base, name):
    if not base or base.endswith((":", "/")):
        return base + name
    return base + "/" + name


def _parent_local(path):
    if not path or path.endswith(":"):
        return path
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
        name = name[:19] + "»"
    return f"{name:<20s} {kind} {stamp}"


class LocalPane(BasePane):
    def __init__(self, path, list_rect, label_rect):
        if path and not path.startswith("s3://") and not os.path.exists(path):
            path = "SYS:"
        super().__init__(path if path else "SYS:", list_rect, label_rect)

    def refresh(self):
        try:
            names = sorted(os.listdir(self.path))
        except OSError as e:
            self.entries = []
            self.list.items = [f"<error: {e.__class__.__name__}: {e}>"]
            return
        self.entries = []
        if self.path and self.path not in ("/", "SYS:", "DH0:", "DH1:") \
                and not self.path.endswith(":"):
            self.entries.append(("..", True, 0, 0))
        for n in names:
            full = _join_local(self.path, n)
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
            self.path = _parent_local(self.path)
        else:
            self.path = _join_local(self.path, name)
        self.refresh()
        return True

    def go_root(self):
        i = self.path.find(":")
        if i > 0:
            self.path = self.path[:i + 1]
        else:
            self.path = "/"
        self.refresh()

    def go_parent(self):
        self.path = _parent_local(self.path)
        self.refresh()

    def read_file(self, name) -> bytes:
        with open(_join_local(self.path, name), "rb") as f:
            return f.read()

    def write_file(self, name, data: bytes):
        with open(_join_local(self.path, name), "wb") as f:
            f.write(data)

    def delete_entry(self, name):
        target = _join_local(self.path, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)

    def mkdir(self, name):
        os.mkdir(_join_local(self.path, name))

    def rename(self, old, new):
        os.rename(_join_local(self.path, old), _join_local(self.path, new))


# ---------------------------------------------------------------------------
# S3Pane — MinIO / AWS via amiga.s3
# ---------------------------------------------------------------------------

def _s3_client_from_env():
    if not _HAS_S3:
        raise RuntimeError("amiga.s3 not available on this build")
    ep = os.environ.get("S3_ENDPOINT", _s3.PLAY_ENDPOINT)
    ak = os.environ.get("S3_ACCESS",   _s3.PLAY_ACCESS)
    sk = os.environ.get("S3_SECRET",   _s3.PLAY_SECRET)
    insecure = os.environ.get("S3_INSECURE", "1") == "1"
    return _s3.S3Client(ep, ak, sk, insecure_tls=insecure)


def _split_s3(path):
    """Split 's3://bucket/prefix/here' into (bucket, prefix). Empty
    strings for the bucket-list level ('s3://')."""
    rest = path[5:] if path.startswith("s3://") else path[3:]
    rest = rest.strip("/")
    if not rest:
        return "", ""
    if "/" not in rest:
        return rest, ""
    bucket, _, prefix = rest.partition("/")
    return bucket, prefix.strip("/")


def _mk_s3(bucket, prefix):
    if not bucket:
        return "s3://"
    if not prefix:
        return f"s3://{bucket}"
    return f"s3://{bucket}/{prefix}"


class S3Pane(BasePane):
    def __init__(self, path, list_rect, label_rect):
        if not path.startswith("s3:"):
            path = "s3://"
        self._client = None
        self._err = None
        super().__init__(path, list_rect, label_rect)

    def _get_client(self):
        if self._client is None:
            try:
                self._client = _s3_client_from_env()
            except Exception as e:
                self._err = str(e)
                raise
        return self._client

    def refresh(self):
        bucket, prefix = _split_s3(self.path)
        # Retry once on empty response — amiga.https shells out to
        # openssl s_client each request, and back-to-back calls can
        # transiently return empty output (subprocess race). One retry
        # with a brief sleep is enough to catch the flaky case
        # without doubling latency in the happy path.
        import time as _t
        try:
            c = self._get_client()
            if not bucket:
                # Bucket-list view: each bucket is a "directory"
                bs = c.list_buckets()
                if not bs:
                    _t.sleep(0.5)
                    bs = c.list_buckets()
                    print(f"S3Pane: retry list_buckets → {len(bs)} entries",
                          flush=True)
                self.entries = [(".." , True, 0, 0)] if False else []
                self.entries += [(b["name"], True, 0, 0) for b in bs]
                self.list.items = [
                    f"{'/' + b['name']:<30s} <BUCKET>" for b in bs
                ]
            else:
                # Object listing scoped to the prefix (path-style).
                prefix_slash = (prefix + "/") if prefix else ""
                objs = c.list_objects(bucket, prefix=prefix_slash,
                                       max_keys=1000)
                if not objs:
                    _t.sleep(0.5)
                    objs = c.list_objects(bucket, prefix=prefix_slash,
                                            max_keys=1000)
                    print(f"S3Pane: retry list_objects → {len(objs)} entries",
                          flush=True)
                self.entries = [("..", True, 0, 0)]
                # Collect sub-"folders" from key prefixes we see.
                seen_folders: set[str] = set()
                files = []
                for o in objs:
                    key = o["key"]
                    rest = key[len(prefix_slash):]
                    if "/" in rest:
                        folder = rest.split("/", 1)[0]
                        if folder and folder not in seen_folders:
                            seen_folders.add(folder)
                            self.entries.append((folder, True, 0, 0))
                    elif rest:
                        files.append((rest, False, o["size"], 0))
                self.entries += sorted(files)
                self.list.items = [_format_row(e) for e in self.entries]
            self.list.selected = 0 if self.entries else -1
            self.list.top = 0
        except Exception as e:
            import traceback
            print(f"S3Pane.refresh({self.path}) FAILED: "
                  f"{type(e).__name__}: {e}\n{traceback.format_exc()}",
                  flush=True)
            self.entries = []
            self.list.items = [f"<S3 error: {type(e).__name__}: {e}>"]
            self.list.selected = -1

    def enter_selected(self):
        e = self.selected_entry()
        if not e:
            return False
        name, is_dir, _, _ = e
        if not is_dir:
            return False
        bucket, prefix = _split_s3(self.path)
        if name == "..":
            if prefix:
                parent = "/".join(prefix.split("/")[:-1])
                self.path = _mk_s3(bucket, parent)
            elif bucket:
                self.path = _mk_s3("", "")   # back to bucket list
            else:
                return False
        elif not bucket:
            # picked a bucket at root
            self.path = _mk_s3(name, "")
        else:
            new_prefix = f"{prefix}/{name}" if prefix else name
            self.path = _mk_s3(bucket, new_prefix)
        self.refresh()
        return True

    def go_parent(self):
        bucket, prefix = _split_s3(self.path)
        if prefix:
            self.path = _mk_s3(bucket, "/".join(prefix.split("/")[:-1]))
        elif bucket:
            self.path = _mk_s3("", "")
        self.refresh()

    def go_root(self):
        self.path = "s3://"
        self.refresh()

    def _key(self, name):
        bucket, prefix = _split_s3(self.path)
        if not bucket:
            raise RuntimeError("no bucket selected")
        rel = f"{prefix}/{name}" if prefix else name
        return bucket, rel

    def read_file(self, name) -> bytes:
        c = self._get_client()
        bucket, key = self._key(name)
        return c.get_object(bucket, key)

    def write_file(self, name, data: bytes):
        c = self._get_client()
        bucket, key = self._key(name)
        c.put_object(bucket, key, data)

    def delete_entry(self, name):
        c = self._get_client()
        bucket, key = self._key(name)
        # NB: if the "entry" is a folder (prefix) this doesn't delete
        # anything — you'd need a recursive list+delete. Skipped here
        # to keep the surface small; delete individual objects only.
        c.delete_object(bucket, key)

    def mkdir(self, name):
        # S3 has no true dirs. Write a zero-byte placeholder so the
        # "folder" shows up in listings under a `/`. Deleting the
        # last object under it makes the folder disappear too — same
        # semantics as most S3 GUIs.
        c = self._get_client()
        bucket, prefix = _split_s3(self.path)
        if not bucket:
            raise RuntimeError("mkdir at s3://root creates buckets — not "
                                "implemented; use `mc mb` on the host")
        rel = f"{prefix}/{name}/.folder" if prefix else f"{name}/.folder"
        c.put_object(bucket, rel, b"")

    def rename(self, old, new):
        # S3 has no atomic rename; copy + delete.
        data = self.read_file(old)
        self.write_file(new, data)
        self.delete_entry(old)


# ---------------------------------------------------------------------------
# Factory — parse a spec into the right pane subclass
# ---------------------------------------------------------------------------

def make_pane(spec, list_rect, label_rect):
    if _HAS_S3 and spec.startswith(("s3:", "S3:")):
        return S3Pane(spec, list_rect, label_rect)
    return LocalPane(spec, list_rect, label_rect)


# ---------------------------------------------------------------------------
# Confirm + prompt dialogs
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
    r = prompt(title, message + "  (leave 'y' + OK to confirm)", "y", 4)
    return r is not None and r.strip().lower().startswith("y")


# ---------------------------------------------------------------------------
# File operations — pane-polymorphic
# ---------------------------------------------------------------------------

def op_copy(app):
    src = app.state["focused"]
    dst = _other(app)
    name = src.selected_name()
    if not name or name == "..":
        _msg(app, "no source selected"); return
    if not confirm("Copy", f"copy {name} to {dst.label()}?"):
        _msg(app, "cancelled"); return
    try:
        data = src.read_file(name)
        dst.write_file(name, data)
        _msg(app, f"copied {name} -> {dst.label()} ({len(data)}b)")
        dst.refresh()
    except Exception as e:
        _msg(app, f"copy failed: {e}")


def op_move(app):
    src = app.state["focused"]
    dst = _other(app)
    name = src.selected_name()
    if not name or name == "..":
        _msg(app, "no source"); return
    if not confirm("Move", f"move {name} to {dst.label()}?"):
        _msg(app, "cancelled"); return
    try:
        data = src.read_file(name)
        dst.write_file(name, data)
        src.delete_entry(name)
        _msg(app, f"moved {name}")
        src.refresh(); dst.refresh()
    except Exception as e:
        _msg(app, f"move failed: {e}")


def op_delete(app):
    src = app.state["focused"]
    name = src.selected_name()
    if not name or name == "..":
        _msg(app, "no target"); return
    if not confirm("Delete", f"delete {name}?"):
        _msg(app, "cancelled"); return
    try:
        src.delete_entry(name)
        _msg(app, f"deleted {name}")
        src.refresh()
    except Exception as e:
        _msg(app, f"delete failed: {e}")


def op_mkdir(app):
    name = prompt("MkDir", "new-dir-name", "", 60)
    if not name or not name.strip():
        _msg(app, "cancelled"); return
    try:
        app.state["focused"].mkdir(name.strip())
        _msg(app, f"created {name}")
        app.state["focused"].refresh()
    except Exception as e:
        _msg(app, f"mkdir failed: {e}")


def op_rename(app):
    src = app.state["focused"]
    name = src.selected_name()
    if not name or name == "..":
        _msg(app, "no target"); return
    new_name = prompt("Rename", f"new name for {name}", name, 100)
    if not new_name or not new_name.strip() or new_name == name:
        _msg(app, "cancelled"); return
    try:
        src.rename(name, new_name.strip())
        _msg(app, f"renamed -> {new_name}")
        src.refresh()
    except Exception as e:
        _msg(app, f"rename failed: {e}")


def op_refresh(app):
    for p in (app.state["left"], app.state["right"]):
        p.refresh()
    _msg(app, "refreshed")


def op_swap(app):
    l, r = app.state["left"], app.state["right"]
    l.path, r.path = r.path, l.path
    # Preserve pane widget positions — swap only paths, then refresh
    # with the new spec. If the swapped path calls for a different
    # pane class (local <-> s3), replace the pane object in place.
    app.state["left"]  = _rebuild(l)
    app.state["right"] = _rebuild(r)
    _rewire_widgets(app)
    _msg(app, "swapped")


def op_setpath(app):
    """Change the focused pane's target. Accepts local paths and
    s3:// URIs; hands off to make_pane() when the storage-class
    changes."""
    focused = app.state["focused"]
    new = prompt("Set path", "path (SYS:  or  s3://bucket/prefix)",
                 focused.path, 200)
    if not new or not new.strip():
        _msg(app, "cancelled"); return
    new = new.strip()
    try:
        replacement = make_pane(new, focused.list_rect, focused.label_rect)
        # Swap it into the app state.
        for side in ("left", "right"):
            if app.state[side] is focused:
                app.state[side] = replacement
                if app.state["focused"] is focused:
                    app.state["focused"] = replacement
                break
        _rewire_widgets(app)
        _msg(app, f"pane now at {replacement.label()}")
    except Exception as e:
        _msg(app, f"set-path failed: {e}")


def op_quit(app):
    app.stop()


def _rebuild(old):
    """After a swap, if the storage class needs to change, build a
    fresh pane of the right class for the new path. If it matches
    already, just refresh() the existing object."""
    if old.path.startswith(("s3:", "S3:")):
        if isinstance(old, S3Pane):
            old.refresh(); return old
        return S3Pane(old.path, old.list_rect, old.label_rect)
    if isinstance(old, LocalPane):
        old.refresh(); return old
    return LocalPane(old.path, old.list_rect, old.label_rect)


def _rewire_widgets(app):
    """Rebuild app.widgets from current panes + buttons. Called
    whenever a pane object is replaced."""
    app.widgets = [app.state["left"].list, app.state["right"].list,
                    *app.state["buttons"]]


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
        text = f"{marker} {pane.label()}"
        if len(text) > 50:
            text = text[:50]
        app.text(x, y, text, PEN_ACC if pane is focus else PEN_FG)

    _draw_pane_header(l,   8, 20)
    _draw_pane_header(r, 408, 20)


def draw_status(app):
    app.fill(4, 388, 812, 404, PEN_BG)
    app.text(8, 400, app.state.get("msg", ""), PEN_HI)


def main():
    left_spec  = os.environ.get("FILEMAN_LEFT",  "SYS:")
    right_spec = os.environ.get("FILEMAN_RIGHT", "DH1:")
    if not right_spec.startswith("s3://") and not os.path.exists(right_spec):
        right_spec = "SYS:"

    app = App(title="Python File Manager (local + S3)",
              w=820, h=440, left=40, top=30)

    left  = make_pane(left_spec,
                       list_rect=Rect(8,   30, 400, 340),
                       label_rect=Rect(8,   16, 400,  30))
    right = make_pane(right_spec,
                       list_rect=Rect(408, 30, 800, 340),
                       label_rect=Rect(408, 16, 800,  30))

    left._on_pick_callback  = lambda a, i, it: a.state.update(focused=left)
    right._on_pick_callback = lambda a, i, it: a.state.update(focused=right)

    app.state["left"]    = left
    app.state["right"]   = right
    app.state["focused"] = left
    app.state["msg"]     = ("focus a pane by clicking, then use a button below. "
                            "Set S3_ENDPOINT/S3_ACCESS/S3_SECRET env vars before "
                            "running to point at your own S3.")

    # Bottom bar
    W = 70
    y0, y1 = 350, 380
    def _btn(x, label, fn):
        return Button(Rect(x, y0, x + W, y1), label, on_click=fn)
    buttons = [
        _btn(  8, "Enter",   lambda a: a.state["focused"].enter_selected() or True),
        _btn( 84, "Up",      lambda a: a.state["focused"].go_parent()),
        _btn(160, "Root",    lambda a: a.state["focused"].go_root()),
        _btn(236, "Set",     op_setpath),
        _btn(312, "Copy",    op_copy),
        _btn(388, "Move",    op_move),
        _btn(464, "Delete",  op_delete),
        _btn(540, "Rename",  op_rename),
        _btn(616, "MkDir",   op_mkdir),
        _btn(692, "Refresh", op_refresh),
        _btn(742, "Quit",    op_quit),
    ]
    app.state["buttons"] = buttons

    app.widgets = [left.list, right.list, *buttons]

    def redraw(a):
        a.clear(PEN_BG)
        draw_header(a)
        a.draw_widgets()
        draw_status(a)

    def on_key(a, ch, code):
        if ch == "q":
            op_quit(a); return True
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
