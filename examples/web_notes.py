#!/usr/bin/env python3
"""web_notes.py — notes app with a local HTTP server.

Split-pane windowed notes editor + a background HTTP server on port
8080 so you can read + create notes from a browser (on the Amiga or
another host on the network).

Left pane:  ScrollableListPanel of note titles.
Right pane: read-only preview of the currently-selected note body.
Bottom:     New / Edit / Delete / Refresh / Serve / Quit buttons +
            a status line with the server URL.

Storage: JSON file at RAM:web_notes.json (RAM: for fast + non-
persistent testing; users can swap to DH1: by editing NOTES_PATH).

HTTP endpoints:
  GET  /              -> HTML index listing every note
  GET  /note/<idx>    -> HTML view of one note
  GET  /raw/<idx>     -> plaintext body
  POST /new           -> form post: title=..., body=...

Runs the HTTP server in a daemon thread so it never blocks the UI
event loop.  Rebuilds the note list from disk each request so
edits made in the GUI are visible immediately in the browser.
"""
import json
import os
import socket
import sys
import threading
import time
from urllib.parse import parse_qs

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga
from amiga.ui import (App, Button, Label, ListPanel, Rect,
                       PEN_FG, PEN_BG, PEN_HI, PEN_ACC)


NOTES_PATH = "RAM:web_notes.json"
HTTP_PORT  = 8080


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

_lock = threading.Lock()

def load_notes():
    with _lock:
        try:
            with open(NOTES_PATH, "r") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []


def save_notes(notes):
    with _lock:
        tmp = NOTES_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(notes, f)
        try:
            os.replace(tmp, NOTES_PATH)
        except OSError:
            # older newlib may not have os.replace on non-existing dest;
            # fall back to unlink + rename.
            try: os.remove(NOTES_PATH)
            except OSError: pass
            os.rename(tmp, NOTES_PATH)


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

INDEX_HTML = """<!doctype html><meta charset="utf-8">
<title>Amiga Web Notes</title>
<style>body{{font:14px sans-serif;max-width:640px;margin:2em auto}}
li{{margin:.4em 0}} form{{margin:2em 0;border:1px solid #ccc;padding:1em}}</style>
<h1>Amiga Web Notes</h1>
<p>Served from Python 3.12.7 running on AmigaOS 4.1 PPC.</p>
<ol>{items}</ol>
<form method=post action=/new>
  <p>New note:</p>
  <p><input name=title style=width:100% placeholder="title"></p>
  <p><textarea name=body rows=6 style=width:100%></textarea></p>
  <p><button>Create</button></p>
</form>
<hr><small>{count} note(s) · <a href=/raw>plain-text dump</a></small>"""


NOTE_HTML = """<!doctype html><meta charset="utf-8">
<title>{title}</title>
<style>body{{font:14px sans-serif;max-width:640px;margin:2em auto}}
pre{{white-space:pre-wrap;background:#f4f4f4;padding:1em}}</style>
<h1>{title}</h1><pre>{body}</pre>
<p><a href=/>&laquo; back to index</a> · <a href=/raw/{idx}>raw text</a></p>"""


def _html_escape(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def _response(status_line, body, ctype="text/html; charset=utf-8", extra=""):
    body_bytes = body.encode("utf-8") if isinstance(body, str) else body
    hdrs = (
        f"HTTP/1.0 {status_line}\r\n"
        f"Content-Type: {ctype}\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        f"{extra}"
        "\r\n"
    )
    return hdrs.encode("ascii") + body_bytes


def _handle_request(raw):
    """raw is the full request bytes.  Returns response bytes."""
    try:
        head, _, rest = raw.partition(b"\r\n\r\n")
        req_line, _, header_block = head.decode("iso-8859-1").partition("\r\n")
        parts = req_line.split(" ", 2)
        if len(parts) < 2:
            return _response("400 Bad Request", "bad request", "text/plain")
        method, path = parts[0], parts[1]
    except Exception:
        return _response("400 Bad Request", "bad request", "text/plain")

    notes = load_notes()

    if method == "GET" and path in ("/", "/index"):
        items = "".join(
            f'<li><a href="/note/{i}">{_html_escape(n["title"] or "(untitled)")}</a></li>'
            for i, n in enumerate(notes))
        return _response("200 OK",
                         INDEX_HTML.format(items=items, count=len(notes)))
    if method == "GET" and path.startswith("/note/"):
        try: idx = int(path[6:])
        except ValueError: return _response("400 Bad Request", "bad index", "text/plain")
        if not (0 <= idx < len(notes)):
            return _response("404 Not Found", "no such note", "text/plain")
        n = notes[idx]
        return _response("200 OK", NOTE_HTML.format(
            idx=idx,
            title=_html_escape(n["title"]),
            body=_html_escape(n["body"])))
    if method == "GET" and path.startswith("/raw/"):
        try: idx = int(path[5:])
        except ValueError: return _response("400 Bad Request", "bad index", "text/plain")
        if not (0 <= idx < len(notes)):
            return _response("404 Not Found", "no such note", "text/plain")
        return _response("200 OK", notes[idx]["body"], "text/plain; charset=utf-8")
    if method == "GET" and path == "/raw":
        body = "\n\n---\n\n".join(
            f"{n['title']}\n\n{n['body']}" for n in notes)
        return _response("200 OK", body, "text/plain; charset=utf-8")
    if method == "POST" and path == "/new":
        # Content-Length may or may not be present; use what we've got.
        form = parse_qs(rest.decode("utf-8", errors="replace"))
        title = (form.get("title", [""])[0]).strip() or "(untitled)"
        text  = (form.get("body",  [""])[0]).strip()
        notes.append({"title": title, "body": text,
                       "created": time.strftime("%Y-%m-%d %H:%M:%S")})
        save_notes(notes)
        return _response("303 See Other", "",
                         extra="Location: /\r\n")
    return _response("404 Not Found", "not found", "text/plain")


def serve_forever(port, ready_evt):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))
        s.listen(4)
    except OSError as e:
        ready_evt.err = str(e); ready_evt.set(); return
    ready_evt.err = None
    ready_evt.set()

    while True:
        try:
            conn, _addr = s.accept()
        except OSError:
            time.sleep(0.5); continue
        # Read request up to end-of-headers (or Content-Length worth for POST).
        try:
            conn.settimeout(3.0)
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk: break
                buf += chunk
                if len(buf) > 65536: break
            # For POST, drain body up to Content-Length.
            if b"\r\n\r\n" in buf:
                header_end = buf.index(b"\r\n\r\n") + 4
                head_txt = buf[:header_end].decode("iso-8859-1", errors="replace")
                clen = 0
                for line in head_txt.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        try: clen = int(line.split(":", 1)[1].strip())
                        except ValueError: pass
                have = len(buf) - header_end
                while have < clen:
                    chunk = conn.recv(min(4096, clen - have))
                    if not chunk: break
                    buf += chunk; have += len(chunk)
            resp = _handle_request(buf)
            conn.sendall(resp)
        except Exception:
            pass
        finally:
            try: conn.close()
            except OSError: pass


# ---------------------------------------------------------------------------
# GUI helpers
# ---------------------------------------------------------------------------

def prompt_form(title, defaults):
    """defaults is [(label, default, maxlen), ...] — returns dict or None."""
    if not hasattr(_amiga, "open_dialog"):
        return None
    h = _amiga.open_dialog(title=title, fields=defaults,
                            ok_label="Save", cancel_label="Cancel",
                            left=140, top=100)
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


def new_note(app):
    r = prompt_form("New Note",
                     [("title", "", 120), ("body", "", 400)])
    if not r or not r.get("title", "").strip():
        app.state["msg"] = "cancelled"; return
    notes = load_notes()
    notes.append({"title": r["title"].strip(),
                    "body":  r.get("body", "").strip(),
                    "created": time.strftime("%Y-%m-%d %H:%M:%S")})
    save_notes(notes)
    refresh(app)
    app.state["msg"] = f"saved: {r['title'][:40]!r}"


def edit_note(app):
    idx = app.state["list"].selected
    notes = load_notes()
    if not (0 <= idx < len(notes)):
        app.state["msg"] = "no note selected"; return
    n = notes[idx]
    r = prompt_form("Edit Note",
                     [("title", n["title"], 120),
                      ("body",  n["body"],  400)])
    if not r:
        app.state["msg"] = "cancelled"; return
    n["title"] = r["title"].strip()
    n["body"]  = r.get("body", "").strip()
    save_notes(notes)
    refresh(app)
    app.state["msg"] = f"edited: {n['title'][:40]!r}"


def delete_note(app):
    idx = app.state["list"].selected
    notes = load_notes()
    if not (0 <= idx < len(notes)):
        app.state["msg"] = "no note selected"; return
    r = prompt_form("Delete Note",
                     [("confirm", "y", 4)])
    if not r or not r.get("confirm", "").lower().startswith("y"):
        app.state["msg"] = "cancelled"; return
    n = notes.pop(idx)
    save_notes(notes)
    refresh(app)
    app.state["msg"] = f"deleted: {n['title'][:40]!r}"


def refresh(app):
    notes = load_notes()
    lst = app.state["list"]
    lst.items = [f"{i+1:>2d}. {n['title'] or '(untitled)'}" for i, n in enumerate(notes)]
    if not (0 <= lst.selected < len(notes)):
        lst.selected = 0 if notes else -1
    app.state["notes"] = notes


def start_server(app):
    if app.state.get("server_started"):
        app.state["msg"] = "server already running"; return
    ready = threading.Event()
    ready.err = None
    t = threading.Thread(target=serve_forever,
                          args=(HTTP_PORT, ready), daemon=True)
    t.start()
    ready.wait(3.0)
    if ready.err:
        app.state["msg"] = f"serve failed: {ready.err}"
    else:
        app.state["server_started"] = True
        app.state["msg"] = f"serving on http://<amiga>:{HTTP_PORT}/"


def quit_app(app):
    app.stop()


# ---------------------------------------------------------------------------
# Draw
# ---------------------------------------------------------------------------

DETAIL_X0 = 320; DETAIL_X1 = 800; DETAIL_Y0 = 20; DETAIL_Y1 = 340
LINE_H = 14


def draw_detail(app):
    app.fill(DETAIL_X0, DETAIL_Y0, DETAIL_X1, DETAIL_Y1, PEN_BG)
    app.line(DETAIL_X0, DETAIL_Y0, DETAIL_X1, DETAIL_Y0, PEN_FG)
    app.line(DETAIL_X0, DETAIL_Y1, DETAIL_X1, DETAIL_Y1, PEN_FG)
    app.line(DETAIL_X0, DETAIL_Y0, DETAIL_X0, DETAIL_Y1, PEN_FG)
    app.line(DETAIL_X1, DETAIL_Y0, DETAIL_X1, DETAIL_Y1, PEN_FG)

    notes = app.state.get("notes", [])
    idx = app.state["list"].selected
    if not (0 <= idx < len(notes)):
        app.text(DETAIL_X0 + 12, DETAIL_Y0 + 24,
                  "pick a note on the left to see body", PEN_FG)
        return
    n = notes[idx]
    app.text(DETAIL_X0 + 12, DETAIL_Y0 + 20, n.get("title", ""), PEN_ACC)
    app.text(DETAIL_X0 + 12, DETAIL_Y0 + 36, n.get("created", ""), PEN_FG)
    y = DETAIL_Y0 + 60
    max_chars = (DETAIL_X1 - DETAIL_X0 - 24) // 8
    for para in n.get("body", "").splitlines() or [""]:
        while para:
            chunk = para[:max_chars]
            app.text(DETAIL_X0 + 12, y, chunk, PEN_FG)
            y += LINE_H
            para = para[max_chars:]
            if y > DETAIL_Y1 - 20:
                return
        y += 4    # blank line between paragraphs


def draw_status(app):
    app.fill(4, 388, 816, 404, PEN_BG)
    app.text(8, 400, app.state.get("msg", ""), PEN_HI)


def main():
    app = App(title="Python Web Notes", w=820, h=440, left=40, top=30)

    lst = ListPanel(rect=Rect(8, 20, 310, 340), items=[], row_h=14,
                     on_pick=lambda a, idx, item: a.request_redraw())
    app.state["list"] = lst
    app.state["msg"] = f"press Serve to start HTTP on port {HTTP_PORT}"
    app.state["server_started"] = False
    refresh(app)

    y0, y1 = 350, 380
    W = 96
    def _btn(x, label, fn):
        return Button(Rect(x, y0, x + W, y1), label, on_click=fn)
    buttons = [
        _btn(  8, "New",     new_note),
        _btn(108, "Edit",    edit_note),
        _btn(208, "Delete",  delete_note),
        _btn(308, "Refresh", lambda a: (refresh(a), a.state.update(msg=f"reloaded {len(a.state['notes'])} note(s)"))),
        _btn(408, "Serve",   start_server),
        _btn(720, "Quit",    quit_app),
    ]

    app.widgets = [Label(8, 4, "Notes", PEN_HI), lst, *buttons]

    def redraw(a):
        a.clear(PEN_BG)
        a.draw_widgets()
        draw_detail(a)
        draw_status(a)

    def on_key(a, ch, code):
        if ch == "q":
            quit_app(a); return True
        if ch == "n":
            new_note(a); return True
        if ch == "e":
            edit_note(a); return True
        if ch == "d":
            delete_note(a); return True
        if ch == "s":
            start_server(a); return True
        return False

    app.redraw = redraw
    app.on_key = on_key
    app.run()


if __name__ == "__main__":
    main()
