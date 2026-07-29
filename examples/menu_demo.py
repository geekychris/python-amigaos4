"""menu_demo.py — Intuition menu bar demo (File/Edit + shortcuts).

Requires the BOOPSI-enabled _amiga build (menu_strip / menu_pick_decode).
Opens a window with a menu bar; each menu-pick prints a line to stdout
and gets logged on-screen.

Menus:
  File  → Open (O), Save (S), ---, Quit (Q)
  Edit  → Copy (C), Paste (V), ---, About

Controls:
  ESC / close gadget  → quit
  Menu picks          → logged in the window

Run:
    python3 python3:examples/menu_demo.py
"""
import sys, os
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga

W, H = 480, 260

MENU_SPEC = [
    ("File", [
        ("Open",  "O"),
        ("Save",  "S"),
        None,                 # separator
        ("Quit",  "Q"),
    ]),
    ("Edit", [
        ("Copy",  "C"),
        ("Paste", "V"),
        None,
        ("About", None),
    ]),
]

# Human-readable name lookup keyed by (menu_num, item_num).
NAMES = {}
for mi, (mtitle, items) in enumerate(MENU_SPEC):
    real_idx = 0
    for it in items:
        if it is None:
            real_idx += 1
            continue
        label = it[0] if isinstance(it, tuple) else it
        NAMES[(mi, real_idx)] = f"{mtitle} → {label}"
        real_idx += 1


def main():
    handle = _amiga.open_window(
        title="Python menu demo",
        left=100, top=80, width=W, height=H,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_MENUPICK),
    )
    print(f"menu_demo: window @ {hex(handle)}", flush=True)
    mshandle = None
    try:
        mshandle = _amiga.set_menu_strip(handle, MENU_SPEC)
        print(f"menu_demo: menu strip @ {hex(mshandle)}", flush=True)
        _amiga.clear_window(handle, 0)

        log = ["Click a menu — File/Edit at the top.",
               "ESC or close to quit."]
        def redraw():
            _amiga.clear_window(handle, 0)
            for i, line in enumerate(log[-15:]):
                _amiga.draw_text(handle, 8, 16 + i * 12, line, 1)
        redraw()

        running = True
        while running:
            ev = _amiga.wait_message(handle, 5.0)
            if ev is None:
                continue
            cls = ev["class"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                running = False
            elif cls == _amiga.IDCMP_VANILLAKEY and ev["code"] == 27:
                running = False
            elif cls == _amiga.IDCMP_MENUPICK:
                code = ev["code"]
                # 0xFFFF or code=~0 signals "end of pick chain".
                if code == 0xFFFF:
                    continue
                menu, item, sub = _amiga.menu_pick_decode(code)
                label = NAMES.get((menu, item), f"?({menu},{item},{sub})")
                msg = f"pick: {label}"
                print(msg, flush=True)
                log.append(msg)
                # File → Quit ends the app.
                if label == "File → Quit":
                    running = False
                redraw()
    finally:
        if mshandle:
            _amiga.clear_menu_strip(mshandle)
        _amiga.close_window(handle)
        print("menu_demo: closed", flush=True)


if __name__ == "__main__":
    main()
