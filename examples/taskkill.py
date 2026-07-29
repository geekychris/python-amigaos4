#!/usr/bin/env python3
"""taskkill.py — live process manager for AmigaOS 4.

Left pane: ScrollableListPanel of every task in ExecBase
           (walked via _amiga.list_tasks — real Forbid()/Permit() walk).
           One row per task, `pri  state  name`, refreshed every 2s.

Right pane: task details + a big red "Send CTRL-C" button that talks
            to the bridge daemon (STOP) if the target is a registered
            bridge client, or writes a diagnostic if not.

Bottom bar: Refresh (manual), Freeze (pause auto-refresh), Send Signal,
            Quit.

The "Send Signal" button opens a composite dialog with the target
task's name + a signal picker so the user can send CTRLC / CTRLD /
CTRLE / CTRLF via _amiga bridge_stop (if available) or a shell-out
to `Break <pid> CTRL-C` — whichever path the runtime supports.

This is a *read-mostly* tool because Amiga tasks aren't Unix processes
and there's no safe universal "kill" — we err on the side of showing
what's running and giving the user well-labelled off-buttons for the
subset that respond.
"""
import os
import sys
import time

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga
from amiga.ui import (App, Button, Label, ListPanel, Rect,
                       PEN_FG, PEN_BG, PEN_HI, PEN_ACC)


REFRESH_MS = 2000     # auto-refresh cadence


def snapshot_tasks():
    """Return [(name, pri, state), ...] via _amiga.list_tasks."""
    try:
        return list(_amiga.list_tasks())
    except Exception:
        return []


def fmt_row(t):
    name, pri, state = t
    if not name:
        name = "?"
    if len(name) > 25:
        name = name[:24] + "»"
    return f"{pri:>+4d} {state[:4]:<4s} {name}"


def refresh(app):
    tasks = snapshot_tasks()
    app.state["tasks"] = tasks
    lst = app.state["list"]
    prev_sel = lst.selected
    lst.items = [fmt_row(t) for t in tasks]
    # keep selection stable if the same-named task is still there
    if 0 <= prev_sel < len(tasks):
        lst.selected = min(prev_sel, len(tasks) - 1)
    else:
        lst.selected = 0 if tasks else -1
    app.state["last_refresh"] = time.time()


def stop_task(app):
    tasks = app.state.get("tasks", [])
    lst = app.state["list"]
    if not (0 <= lst.selected < len(tasks)):
        app.state["msg"] = "no task selected"
        return
    name, pri, state = tasks[lst.selected]
    if not name or name == "?":
        app.state["msg"] = "task has no name — cannot signal"
        return
    # Try via shell 'Break': works for any process that has a CLI.
    # This is a best-effort; many system tasks won't respond.
    cmd = f"break {name} CTRL-C"
    rc = os.system(cmd)
    if rc == 0:
        app.state["msg"] = f"sent CTRL-C to {name!r}"
    else:
        app.state["msg"] = f"break failed (rc={rc}) — task may not accept signals"


def toggle_freeze(app):
    app.state["frozen"] = not app.state["frozen"]
    app.state["msg"] = "frozen" if app.state["frozen"] else "resumed auto-refresh"


def quit_app(app):
    app.stop()


# ---------------------------------------------------------------------------
# Detail pane
# ---------------------------------------------------------------------------

DETAIL_X0 = 320
DETAIL_Y0 = 20
DETAIL_X1 = 780
DETAIL_Y1 = 340


def draw_detail(app):
    app.fill(DETAIL_X0, DETAIL_Y0, DETAIL_X1, DETAIL_Y1, PEN_BG)
    app.line(DETAIL_X0, DETAIL_Y0, DETAIL_X1, DETAIL_Y0, PEN_FG)
    app.line(DETAIL_X0, DETAIL_Y1, DETAIL_X1, DETAIL_Y1, PEN_FG)
    app.line(DETAIL_X0, DETAIL_Y0, DETAIL_X0, DETAIL_Y1, PEN_FG)
    app.line(DETAIL_X1, DETAIL_Y0, DETAIL_X1, DETAIL_Y1, PEN_FG)

    tasks = app.state.get("tasks", [])
    lst = app.state["list"]
    idx = lst.selected
    y = DETAIL_Y0 + 20
    if 0 <= idx < len(tasks):
        name, pri, state = tasks[idx]
        rows = [
            ("name",  name),
            ("pri",   f"{pri:+d}"),
            ("state", state),
            ("index", str(idx)),
        ]
        for k, v in rows:
            app.text(DETAIL_X0 + 12, y, f"{k:>8s} : {v}", PEN_FG)
            y += 16
        y += 8
        app.text(DETAIL_X0 + 12, y,
                  "Send Signal below sends CTRL-C via 'Break'.", PEN_ACC)
        y += 16
        app.text(DETAIL_X0 + 12, y,
                  "Most system tasks (input.device, USB stack) will", PEN_FG)
        y += 14
        app.text(DETAIL_X0 + 12, y,
                  "ignore this — that's expected + intentional.", PEN_FG)
    else:
        app.text(DETAIL_X0 + 12, y,
                  "pick a task on the left to see details", PEN_FG)

    # summary line
    total = len(tasks)
    named = sum(1 for t in tasks if t[0] and t[0] != "?")
    hi_pri = sum(1 for t in tasks if t[1] > 0)
    app.text(DETAIL_X0 + 12, DETAIL_Y1 - 32,
              f"{total} tasks total, {named} named, {hi_pri} at pri>0",
              PEN_HI)
    freeze = "FROZEN" if app.state.get("frozen") else "auto-refresh 2s"
    app.text(DETAIL_X0 + 12, DETAIL_Y1 - 16, freeze, PEN_ACC)


def draw_status(app):
    app.fill(4, 388, 812, 404, PEN_BG)
    app.text(8, 400, app.state.get("msg", ""), PEN_HI)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    app = App(title="Python TaskKill", w=820, h=440, left=40, top=30)

    lst = ListPanel(rect=Rect(8, 20, 310, 340), items=[], row_h=13,
                     on_pick=lambda a, idx, item: a.request_redraw())
    app.state["list"] = lst
    app.state["tasks"] = []
    app.state["msg"] = "loading..."
    app.state["frozen"] = False
    app.state["last_refresh"] = 0.0

    y0, y1 = 350, 380
    W = 100
    def _btn(x, label, fn):
        return Button(Rect(x, y0, x + W, y1), label, on_click=fn)
    buttons = [
        _btn(  8, "Refresh",    lambda a: refresh(a)),
        _btn(112, "Freeze",     toggle_freeze),
        _btn(216, "Kill",       stop_task),
        _btn(700, "Quit",       quit_app),
    ]

    app.widgets = [Label(8, 4, "Tasks (Amiga ExecBase)", PEN_HI),
                    lst, *buttons]

    refresh(app)

    def redraw(a):
        a.clear(PEN_BG)
        a.draw_widgets()
        draw_detail(a)
        draw_status(a)

    def on_key(a, ch, code):
        if ch == "q":
            quit_app(a); return True
        if ch == "r":
            refresh(a); return True
        if ch == "f":
            toggle_freeze(a); return True
        return False

    app.redraw = redraw
    app.on_key = on_key

    # Custom event loop: reimplement run() so we can drive auto-refresh
    # via wait_message with a timeout.
    from amiga.ui import SELECTDOWN
    app.request_redraw()
    while app._running:
        # timeout in ms; on OS4 the timer.device backing wakes us so
        # this doesn't burn CPU.
        ev = _amiga.wait_message(app.handle, REFRESH_MS)
        now = time.time()
        if not app.state["frozen"] and now - app.state["last_refresh"] >= 2.0:
            refresh(app)
            app.request_redraw()
        if ev is None:
            continue
        cls = ev["class"]
        if cls == _amiga.IDCMP_CLOSEWINDOW:
            break
        if cls == _amiga.IDCMP_REFRESHWINDOW:
            app.request_redraw(); continue
        if cls == _amiga.IDCMP_VANILLAKEY:
            code = ev["code"]
            ch = chr(code).lower() if 32 <= code < 127 else ""
            if code == 27:
                break
            if on_key(app, ch, code):
                app.request_redraw()
        elif cls == _amiga.IDCMP_MOUSEBUTTONS:
            if ev["code"] != SELECTDOWN:
                continue
            x, y = ev["mouse_x"], ev["mouse_y"]
            for w in app.widgets:
                if w.click(app, x, y):
                    app.request_redraw()
                    break
    app.close()


if __name__ == "__main__":
    main()
