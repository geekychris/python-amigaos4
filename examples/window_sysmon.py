"""window_sysmon.py — Python system monitor in a real Intuition window.

Companion to the TUI sysmon.py.  Opens a windowed dashboard:
  - Free memory (any / chip / fast)
  - Task count + top 3 by priority
  - Library count + top 3 by open-count
  - Uptime

Refreshes every 2 seconds unless the user is interacting with the
window (drag/resize/etc).  Exits on close-gadget or ESC.

Run:
    python3 python3:examples/window_sysmon.py
"""
import sys, os, time
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import _amiga
except ImportError:
    print("window_sysmon: needs _amiga native module (Phase 6.5)")
    sys.exit(1)


def draw_stats(handle):
    """Wipe the window and redraw the current stats."""
    mem = _amiga.avail_mem_summary()
    tasks = _amiga.list_tasks()
    libs = _amiga.list_libraries()

    top_tasks = sorted(tasks, key=lambda t: -t[1])[:3]
    top_libs = sorted(libs, key=lambda l: -l[3])[:3]

    _amiga.clear_window(handle, 0)

    y = 12
    line = 14
    _amiga.draw_text(handle, 8, y, "=== Python Sysmon (Intuition) ===", 2)
    y += line * 2

    _amiga.draw_text(handle, 8, y,
        f"Memory:  any {mem['any'] // 1024:>8} KB  chip {mem['chip'] // 1024:>6} KB",
        1)
    y += line
    _amiga.draw_text(handle, 8, y,
        f"         fast {mem['fast'] // 1024:>7} KB  largest {mem['largest'] // 1024:>6} KB",
        1)
    y += line * 2

    _amiga.draw_text(handle, 8, y, f"Tasks: {len(tasks)}  |  Top by priority:", 1)
    y += line
    for name, pri, state in top_tasks:
        s = f"  {pri:>+4} {state[:1]}  {name}"
        _amiga.draw_text(handle, 8, y, s[:56], 1)
        y += line
    y += 4

    _amiga.draw_text(handle, 8, y, f"Libs: {len(libs)}  |  Top by open-count:", 1)
    y += line
    for name, v, r, oc in top_libs:
        s = f"  v{v}.{r:<3} {oc:>3}x  {name}"
        _amiga.draw_text(handle, 8, y, s[:56], 1)
        y += line

    y += line
    _amiga.draw_text(handle, 8, y,
        f"Refreshed {time.strftime('%H:%M:%S')} | ESC or close to exit.", 3)


def main():
    handle = _amiga.open_window(
        title="Python Sysmon",
        left=140, top=90, width=480, height=280,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_REFRESHWINDOW
               | _amiga.IDCMP_NEWSIZE),
    )
    try:
        print(f"window_sysmon: opened window {hex(handle)}")
        running = True
        last_draw = 0.0
        while running:
            now = time.monotonic()
            if now - last_draw > 2.0:
                draw_stats(handle)
                last_draw = now
            ev = _amiga.wait_message(handle, 0.5)
            if ev is None:
                continue
            cls = ev["class"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                running = False
            elif cls == _amiga.IDCMP_VANILLAKEY and ev["code"] == 27:
                running = False
            elif cls in (_amiga.IDCMP_REFRESHWINDOW, _amiga.IDCMP_NEWSIZE):
                # Force redraw on next tick.
                last_draw = 0.0
    finally:
        _amiga.close_window(handle)
        print("window_sysmon: closed.")


if __name__ == "__main__":
    main()
