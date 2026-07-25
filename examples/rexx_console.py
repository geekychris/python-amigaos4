#!/usr/bin/env python3
"""rexx_console.py — clickable ARexx console for AmigaOS 4.1.

Left pane:  scrollable list of currently-detected ARexx ports.  Click
            one to select it as the target for the next command.

Right pane: transcript of commands sent + responses received.  Also
            shows the currently-selected target and inline error messages.

Bottom bar: [Enter Cmd] opens a composite dialog (StringGadget) where
            you type the ARexx command.  [Refresh] rescans ports.
            [REXX Script] pops a dialog for an inline REXX script to
            hand to the interpreter.  [Quit] closes the window.

Every RXCOMM exchange runs on the calling task with a fresh reply
port, so there's no cross-command state to worry about — each click
is one round-trip.

Requires _amiga with rexx_send/rexx_execute/list_rexx_ports (added in
the ARexx-support patch).
"""
import sys
import time

# Prefer our packaged bindings over any stub in the default path.
sys.path.insert(0, "DH1:pytests/amiga_bindings")

try:
    import _amiga
except ImportError:
    print("_amiga native module not available")
    sys.exit(1)

from amiga.ui import App, Button, Label, ListPanel, Rect, PEN_FG, PEN_BG, PEN_HI, PEN_ACC


REXX_AVAILABLE = all(hasattr(_amiga, n) for n in
                     ("list_rexx_ports", "rexx_send", "rexx_execute"))


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class Console:
    def __init__(self):
        self.ports = []
        self.target = None
        self.transcript = []      # list[(kind, text)]  kind in {"info","cmd","ok","err"}
        self.refresh_ports()

    def refresh_ports(self):
        try:
            self.ports = _amiga.list_rexx_ports() if REXX_AVAILABLE else []
        except Exception as e:
            self.log("err", f"list_rexx_ports failed: {e}")
            self.ports = []
        if self.target and self.target not in self.ports:
            self.log("info", f"target '{self.target}' vanished")
            self.target = None
        self.log("info", f"scan: {len(self.ports)} port(s)")

    def log(self, kind, text):
        ts = time.strftime("%H:%M:%S")
        # keep only last 200 rows to bound the redraw work
        self.transcript.append((kind, f"{ts} {text}"))
        if len(self.transcript) > 200:
            self.transcript = self.transcript[-200:]

    def send(self, command):
        if not self.target:
            self.log("err", "no target port selected — click a port on the left")
            return
        self.log("cmd", f">{self.target} : {command}")
        try:
            result = _amiga.rexx_send(self.target, command)
            self.log("ok", f"< {result!r}")
        except Exception as e:
            self.log("err", f"! {e}")

    def execute(self, script):
        self.log("cmd", f">REXX : {script}")
        try:
            result = _amiga.rexx_execute(script)
            self.log("ok", f"< {result!r}")
        except Exception as e:
            self.log("err", f"! {e}")


# ---------------------------------------------------------------------------
# Dialogs — one-field composite prompts via _amiga.open_dialog
# ---------------------------------------------------------------------------

def prompt_one(title, label, default="", maxlen=200):
    """Return the entered string, or None on Cancel."""
    if not hasattr(_amiga, "open_dialog"):
        # graceful degrade — no dialog, no prompt
        return default or None
    handle = _amiga.open_dialog(
        title=title,
        fields=[(label, default, maxlen)],
        ok_label="OK",
        cancel_label="Cancel",
        left=200, top=140,
    )
    try:
        r = _amiga.run_dialog(handle)
    finally:
        _amiga.close_dialog(handle)
    if r is None:
        return None
    return r.get(label, default)


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------

TRANSCRIPT_LEFT = 260
ROW_H = 12


def draw_target_banner(app, console):
    app.fill(TRANSCRIPT_LEFT, 20, 800, 40, PEN_HI)
    label = f"Target: {console.target or '(none — pick a port on the left)'}"
    app.text(TRANSCRIPT_LEFT + 6, 34, label, PEN_FG)


def draw_transcript(app, console):
    top = 50
    bot = 340
    app.fill(TRANSCRIPT_LEFT, top, 800, bot, PEN_BG)
    app.line(TRANSCRIPT_LEFT, top, 800, top, PEN_FG)
    app.line(TRANSCRIPT_LEFT, bot, 800, bot, PEN_FG)
    app.line(TRANSCRIPT_LEFT, top, TRANSCRIPT_LEFT, bot, PEN_FG)
    app.line(800, top, 800, bot, PEN_FG)

    n_rows = (bot - top - 4) // ROW_H
    rows = console.transcript[-n_rows:]
    y = top + ROW_H
    max_chars = (800 - TRANSCRIPT_LEFT - 12) // 8
    for kind, text in rows:
        if len(text) > max_chars:
            text = text[:max_chars]
        pen = {
            "info": PEN_FG,
            "cmd":  PEN_ACC,
            "ok":   PEN_FG,
            "err":  PEN_ACC,   # ideally red pen, but Acc is at least visible
        }.get(kind, PEN_FG)
        app.text(TRANSCRIPT_LEFT + 6, y, text, pen)
        y += ROW_H


def rebuild_port_list(app, console):
    port_list = app.state["port_list"]
    port_list.items = list(console.ports) or ["(no ports)"]
    if console.target and console.target in port_list.items:
        port_list.selected = port_list.items.index(console.target)
    else:
        port_list.selected = -1


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def on_pick_port(app, idx, item):
    if item == "(no ports)":
        return
    console = app.state["console"]
    console.target = item
    console.log("info", f"target set: {item}")


def on_refresh(app):
    console = app.state["console"]
    console.refresh_ports()
    rebuild_port_list(app, console)


def on_send_cmd(app):
    console = app.state["console"]
    if not console.target:
        console.log("err", "pick a port first")
        return
    cmd = prompt_one("Send ARexx Command",
                     f"{console.target}>",
                     default=app.state.get("last_cmd", "VERSION"),
                     maxlen=200)
    if cmd is None or not cmd.strip():
        return
    app.state["last_cmd"] = cmd
    console.send(cmd)


def on_exec_script(app):
    console = app.state["console"]
    script = prompt_one("Inline REXX Script",
                        "REXX>",
                        default=app.state.get("last_script",
                                              "return 6 * 7"),
                        maxlen=200)
    if script is None or not script.strip():
        return
    app.state["last_script"] = script
    console.execute(script)


def on_quit(app):
    app.stop()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not REXX_AVAILABLE:
        print("This _amiga build lacks ARexx support — rebuild python-os4 "
              "with the arexx patch (rexx_send / rexx_execute / list_rexx_ports).")
        sys.exit(1)

    console = Console()

    app = App(
        title="Python ARexx Console",
        w=820, h=400,
        left=60, top=40,
    )
    app.state["console"] = console
    app.state["last_cmd"] = "VERSION"
    app.state["last_script"] = "return 6 * 7"

    # Left: port list (with title above)
    port_list = ListPanel(
        rect=Rect(10, 50, 245, 340),
        items=[],
        on_pick=on_pick_port,
        row_h=14,
    )
    app.state["port_list"] = port_list
    rebuild_port_list(app, console)

    # Bottom bar buttons
    btn_refresh = Button(Rect(10,  350, 120, 380), "Refresh",     on_click=on_refresh)
    btn_send    = Button(Rect(130, 350, 260, 380), "Send Cmd",    on_click=on_send_cmd)
    btn_script  = Button(Rect(270, 350, 400, 380), "REXX Script", on_click=on_exec_script)
    btn_quit    = Button(Rect(720, 350, 800, 380), "Quit",        on_click=on_quit)

    app.widgets = [
        Label(10, 20, "ARexx Ports",  PEN_FG),
        port_list,
        btn_refresh, btn_send, btn_script, btn_quit,
    ]

    def redraw(a):
        a.clear(PEN_BG)
        a.draw_widgets()
        draw_target_banner(a, console)
        draw_transcript(a, console)

    app.redraw = redraw
    app.run()


if __name__ == "__main__":
    main()
