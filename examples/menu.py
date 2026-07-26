#!/usr/bin/env python3
"""menu.py — click-driven launcher for every python-amigaos4 demo.

Shows a scrollable list of every example on the left, a short blurb
for the highlighted item on the right, and Run / Refresh / Quit
buttons across the bottom.  Clicking Run (or double-clicking a row)
shells out to the corresponding AmigaDOS launcher script under
DH1:scripts/ so the child inherits its own env + shell.

Because the launchers already set PYTHONHOME + PYTHONPATH the child
demo starts identically to how you'd run it from the shell — no env
plumbing on the menu side.

Requires _amiga (built with dialog + rexx + window support) and the
amiga.ui widget framework at DH1:pytests/amiga_bindings/amiga/ui/.
"""
import os
import sys

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga
from amiga.ui import App, Button, ListPanel, Label, Rect, PEN_FG, PEN_BG, PEN_HI, PEN_ACC


# --- catalogue ---------------------------------------------------------------
# (launcher, title, blurb)
DEMOS = [
    ("clock",            "Clock",
        "Real Intuition window with live time.  ESC or close to exit."),
    ("window_sysmon",    "System Monitor (windowed)",
        "Live task/memory/library dashboard drawn with draw_text."),
    ("sysmon",           "System Monitor (TUI)",
        "Text-mode version of the sysmon; prints to the CLI."),
    ("planner",          "Planner",
        "SQLite-backed calendar + notes with click-through day view."),
    ("snake",            "Snake",
        "freegames snake on amiga.turtle — arrow keys steer."),
    ("snake_verifiable", "Snake (verifiable)",
        "Snake with a scripted key sequence for automated testing."),
    ("gui_form",         "Requester Form",
        "RequestChoice + RequestString-driven wizard demo."),
    ("hello_gui",        "Hello GUI",
        "Simple windowed hello world."),
    ("hello_dos",        "Hello DOS",
        "Minimal shell-out to Info / GetCurrentDirName."),
    ("hello_ipc",        "Hello IPC",
        "amiga.exec MsgPort / Signal / Wait demo."),
    ("port_service",     "Port Service",
        "MsgPort microservice that answers requests from other tasks."),
    ("task_watcher",     "Task Watcher",
        "Poll list_tasks for task spawn / exit events."),
    ("arexx_demo",       "ARexx Demo (text)",
        "Enumerate ARexx ports + drive REXX inline; text-mode."),
    ("rexx_console",     "ARexx Console (GUI)",
        "Clickable REXX playground: pick a port, send commands live."),
    ("fileman",          "File Manager",
        "Dual-pane file manager with Copy/Move/Delete/MkDir."),
    ("taskkill",         "Task Manager",
        "Live process list with details + Break signal button."),
    ("web_notes",        "Web Notes",
        "Notes editor that also serves them over HTTP on port 8080."),
    ("browser",          "HTTP Browser",
        "URL bar + bookmarks + HTML/RSS text-only renderer."),
]


# --- helpers -----------------------------------------------------------------

def launch(app):
    """Run the currently-selected launcher via AmigaDOS Execute."""
    lst = app.state["list"]
    idx = lst.selected
    if idx < 0:
        app.state["msg"] = "select a demo first"
        return
    slug, title, _ = DEMOS[idx]
    cmd = f"execute DH1:scripts/{slug}"
    app.state["msg"] = f"launching {title!r} ..."
    # Fire it in the background so the menu window keeps running.
    # AmigaDOS 'run' does that; wrap it around 'execute <launcher>'.
    os.system(f"run execute DH1:scripts/{slug}")


def refresh(app):
    lst = app.state["list"]
    lst.items = [f"{t}" for _, t, _ in DEMOS]
    app.state["msg"] = f"{len(DEMOS)} demos available"


def quit_menu(app):
    app.stop()


def on_pick(app, idx, item):
    app.state["msg"] = DEMOS[idx][2]


# --- drawing (right pane) ----------------------------------------------------

BLURB_LEFT = 260
BLURB_TOP  = 20
BLURB_RIGHT = 800
BLURB_BOT  = 320

def draw_right_pane(app):
    app.fill(BLURB_LEFT, BLURB_TOP, BLURB_RIGHT, BLURB_BOT, PEN_BG)
    app.line(BLURB_LEFT, BLURB_TOP, BLURB_RIGHT, BLURB_TOP, PEN_FG)
    app.line(BLURB_LEFT, BLURB_BOT, BLURB_RIGHT, BLURB_BOT, PEN_FG)
    app.line(BLURB_LEFT, BLURB_TOP, BLURB_LEFT, BLURB_BOT, PEN_FG)
    app.line(BLURB_RIGHT, BLURB_TOP, BLURB_RIGHT, BLURB_BOT, PEN_FG)

    lst = app.state["list"]
    idx = lst.selected
    if 0 <= idx < len(DEMOS):
        slug, title, blurb = DEMOS[idx]
        app.text(BLURB_LEFT + 8, BLURB_TOP + 20, f"{title}", PEN_ACC)
        app.text(BLURB_LEFT + 8, BLURB_TOP + 36, f"launcher: DH1:scripts/{slug}", PEN_FG)
        # wrap the blurb by hand — no font-metric API
        max_chars = (BLURB_RIGHT - BLURB_LEFT - 16) // 8
        y = BLURB_TOP + 60
        words = blurb.split()
        line = ""
        for w in words:
            if len(line) + 1 + len(w) > max_chars:
                app.text(BLURB_LEFT + 8, y, line, PEN_FG)
                y += 14
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            app.text(BLURB_LEFT + 8, y, line, PEN_FG)
    else:
        app.text(BLURB_LEFT + 8, BLURB_TOP + 20,
                 "pick a demo on the left, then click Run.", PEN_FG)

    # status line under the blurb
    app.text(BLURB_LEFT + 8, BLURB_BOT - 8, app.state.get("msg", ""), PEN_ACC)


# --- main --------------------------------------------------------------------

def main():
    app = App(title="Python Demo Menu",
              w=820, h=380,
              left=60, top=40)

    lst = ListPanel(rect=Rect(10, 20, 250, 320),
                     items=[t for _, t, _ in DEMOS],
                     on_pick=on_pick,
                     row_h=16)
    lst.selected = 0
    app.state["list"] = lst
    app.state["msg"] = f"{len(DEMOS)} demos available"

    btn_run     = Button(Rect(10,  330, 180, 360), "Run",     on_click=launch)
    btn_refresh = Button(Rect(190, 330, 360, 360), "Refresh", on_click=refresh)
    btn_quit    = Button(Rect(720, 330, 800, 360), "Quit",    on_click=quit_menu)

    app.widgets = [Label(10, 4, "Demos", PEN_HI), lst,
                    btn_run, btn_refresh, btn_quit]

    def redraw(a):
        a.clear(PEN_BG)
        a.draw_widgets()
        draw_right_pane(a)

    app.redraw = redraw

    def on_key(a, ch, code):
        if ch == "r":
            launch(a); return True
        if ch == "q":
            quit_menu(a); return True
        # Arrow up/down cycle selection.
        if code == 14:      # up-arrow VANILLAKEY? actually via RAWKEY only
            pass
        return False

    app.on_key = on_key
    app.run()


if __name__ == "__main__":
    main()
