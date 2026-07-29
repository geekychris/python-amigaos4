"""clock.py — Python opens a real Intuition window on Workbench and
draws the current time, refreshed every second.

Uses _amiga's real intuition wrappers (open_window / clear_window /
draw_text / wait_message / close_window).  Runs until the user clicks
the close gadget or presses ESC.

Run:
    python3 python3:examples/clock.py
"""
import sys, os, time
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import _amiga
except ImportError:
    print("clock: needs _amiga native module with Intuition (Phase 6.5)")
    sys.exit(1)


def main():
    handle = _amiga.open_window(
        title="Python Clock",
        left=200, top=150, width=250, height=90,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_REFRESHWINDOW),
    )
    try:
        _amiga.clear_window(handle, 0)
        print(f"clock: window opened at {hex(handle)}")

        running = True
        while running:
            # Redraw the time.
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            uptime = time.monotonic()
            _amiga.clear_window(handle, 0)
            _amiga.draw_text(handle, 8,  15, now, 1)
            _amiga.draw_text(handle, 8,  35, f"Uptime: {uptime:.0f}s", 1)
            _amiga.draw_text(handle, 8,  55, "Press ESC or close to exit.", 1)

            # Wait up to 1s for an event; return None on timeout → tick.
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
        print("clock: closed.")


if __name__ == "__main__":
    main()
