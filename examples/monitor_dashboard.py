"""monitor_dashboard.py — 4-panel live system monitor in one Intuition window.

Divides the window into quadrants:

    ┌───────────────┬───────────────┐
    │  Top Tasks    │  Memory       │
    ├───────────────┼───────────────┤
    │  Libraries    │  MsgPorts     │
    └───────────────┴───────────────┘

Each panel refreshes every second. Beefier than window_sysmon.py —
shows how much you can pack in with just draw_text + fill_rect.

Controls:
    ESC / close → quit

Run:
    python3 python3:examples/monitor_dashboard.py
"""
import sys, time
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga

W, H     = 640, 400
COL_W    = W // 2
ROW_H    = H // 2
PANEL_PAD = 6
TITLE_PEN = 3       # highlight
TEXT_PEN  = 1       # normal
DIM_PEN   = 2       # dim
BG        = 0
LINE_H    = 11      # font line height on default screen


def _draw_panel_frame(win, x, y, w, h, title):
    """Fill panel background + draw the title bar."""
    _amiga.fill_rect(win, x, y, x + w - 1, y + h - 1, BG)
    _amiga.fill_rect(win, x, y, x + w - 1, y + LINE_H + 2, DIM_PEN)
    _amiga.draw_text(win, x + PANEL_PAD, y + LINE_H - 2, title, TEXT_PEN)


def draw_tasks(win, x, y, w, h):
    _draw_panel_frame(win, x, y, w, h, "Top Tasks (by priority)")
    tasks = _amiga.list_tasks()
    top = sorted(tasks, key=lambda t: -t[1])[:8]
    ty = y + LINE_H + 4 + PANEL_PAD
    _amiga.draw_text(win, x + PANEL_PAD, ty,
                     f"{'PRI':>4} {'STATE':<8} NAME", DIM_PEN)
    ty += LINE_H + 2
    for name, pri, state in top:
        if ty + LINE_H >= y + h:
            break
        line = f"{pri:>4} {state:<8} {name[:25]}"
        _amiga.draw_text(win, x + PANEL_PAD, ty, line, TEXT_PEN)
        ty += LINE_H


def draw_mem(win, x, y, w, h):
    _draw_panel_frame(win, x, y, w, h, "Memory")
    s = _amiga.avail_mem_summary()
    lines = [
        f"Chip free : {s['free_chip']:>12,} B",
        f"Fast free : {s['free_fast']:>12,} B",
        f"Total free: {s['free_any']:>12,} B",
        f"Chip largest: {s['largest_chip']:>10,} B",
        f"Fast largest: {s['largest_fast']:>10,} B",
    ]
    ty = y + LINE_H + 4 + PANEL_PAD
    for line in lines:
        if ty + LINE_H >= y + h:
            break
        _amiga.draw_text(win, x + PANEL_PAD, ty, line, TEXT_PEN)
        ty += LINE_H


def draw_libs(win, x, y, w, h):
    _draw_panel_frame(win, x, y, w, h, "Libraries")
    libs = _amiga.list_libraries()
    libs_sorted = sorted(libs, key=lambda l: -l[1])[:8]
    ty = y + LINE_H + 4 + PANEL_PAD
    _amiga.draw_text(win, x + PANEL_PAD, ty,
                     f"{'OPEN':>4} {'V':>4}  NAME", DIM_PEN)
    ty += LINE_H + 2
    for name, opencnt, version, revision in libs_sorted:
        if ty + LINE_H >= y + h:
            break
        v = f"{version}.{revision}"
        line = f"{opencnt:>4} {v:>4}  {name[:25]}"
        _amiga.draw_text(win, x + PANEL_PAD, ty, line, TEXT_PEN)
        ty += LINE_H


def draw_ports(win, x, y, w, h):
    _draw_panel_frame(win, x, y, w, h, "MsgPorts")
    ports = _amiga.list_ports()
    # Amiga typically has ~15 public ports; sort by name for stability.
    ports_sorted = sorted(ports, key=lambda p: p[0].lower())[:10]
    ty = y + LINE_H + 4 + PANEL_PAD
    for entry in ports_sorted:
        # list_ports may return (name,) or (name, sigbit, tasktype) —
        # accept both shapes.
        name = entry[0] if isinstance(entry, tuple) else entry
        if ty + LINE_H >= y + h:
            break
        _amiga.draw_text(win, x + PANEL_PAD, ty, name[:30], TEXT_PEN)
        ty += LINE_H


def main():
    handle = _amiga.open_window(
        title="Python Dashboard",
        left=40, top=30, width=W, height=H,
        idcmp=_amiga.IDCMP_CLOSEWINDOW | _amiga.IDCMP_VANILLAKEY,
    )
    print(f"dashboard: window @ {hex(handle)}", flush=True)
    try:
        running = True
        while running:
            draw_tasks(handle, 0,     0,     COL_W, ROW_H)
            draw_mem(  handle, COL_W, 0,     COL_W, ROW_H)
            draw_libs( handle, 0,     ROW_H, COL_W, ROW_H)
            draw_ports(handle, COL_W, ROW_H, COL_W, ROW_H)

            # Wait up to 1s for an event → next refresh tick.
            ev = _amiga.wait_message(handle, 1.0)
            if ev is None:
                continue
            cls = ev["class"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                running = False
            elif cls == _amiga.IDCMP_VANILLAKEY and ev["code"] == 27:
                running = False
    finally:
        _amiga.close_window(handle)
        print("dashboard: closed", flush=True)


if __name__ == "__main__":
    main()
