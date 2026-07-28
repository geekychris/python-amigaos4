"""reaction_form.py — real ReAction window with layout.gadget.

Matches the canonical Hyperion SDK 54.25 pattern in
    refs/os4-sdk/base/Examples/GUI/Window/Window.c
Two things that mattered:
  1. IDoMethod(obj, WM_OPEN) takes TWO args — no trailing NULL/0.
     A stray zero appears to poison the method payload and
     window.class silently returns NULL.
  2. layout.gadget children attach reliably via LAYOUT_AddChild in
     the initial NewObject tag list — needs new_object_multi
     because dict keys aren't unique.

Layout: vertical LayoutGroup containing labeled Name/Age/Email/Notes
fields + a horizontal button row (OK/Cancel).

If the BOOPSI path still fails on this build, falls back to
_amiga.open_dialog so you always get a usable form.
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga


ID_NAME, ID_AGE, ID_EMAIL, ID_NOTES = 10, 11, 12, 13
ID_OK, ID_CANCEL = 1, 2


def fallback_dialog():
    h = _amiga.open_dialog(
        title="New person",
        fields=[("Name",  "",                40),
                ("Age",   "30",               5),
                ("Email", "you@example.com", 60),
                ("Notes", "",               120)],
        ok_label="Save", cancel_label="Cancel",
        left=140, top=100,
    )
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


def try_reaction():
    """Return (win_obj, intuiwin) or (None, 0) on failure."""
    if not (hasattr(_amiga, "new_object_multi")
            and hasattr(_amiga, "do_method")
            and hasattr(_amiga, "WM_OPEN")):
        print("try_reaction: _amiga missing required attrs", flush=True)
        return (None, 0)

    def _log(msg):
        print(f"try_reaction: {msg}", flush=True)

    try:
        # Mirror refs/os4-sdk/base/Examples/GUI/Window/Window.c line
        # by line. Simplest possible: one button, one layout, one
        # window, WM_OPEN. Get *this* working first, then re-add the
        # form gadgets.
        _log("new_object button ...")
        ok = _amiga.new_object("button.gadget", {
            "GA_ID": ID_OK, "GA_Text": "Click Me",
            "GA_RelVerify": True,
        })
        _log(f"  ok={hex(ok)}")

        _log("new_object_multi layout ...")
        root = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 1),         # LAYOUT_ORIENT_VERT
            ("LAYOUT_SpaceOuter", True),
            ("LAYOUT_AddChild", ok),
        ])
        _log(f"  root={hex(root)}")

        _log("new_object window.class (string name, no OpenClass) ...")
        win = _amiga.new_object_multi("window.class", [
            # WA_ScreenTitle omitted — not in TAG_TABLE yet, dropping
            # to prove the rest of the recipe. Add to _amigamodule.c
            # in a later rebuild if we want a screen title.
            ("WA_Title",       "Python ReAction"),
            ("WA_Activate",    True),
            ("WA_DepthGadget", True),
            ("WA_DragBar",     True),
            ("WA_CloseGadget", True),
            ("WA_SizeGadget",  True),
            ("WINDOW_Position", 4),            # WPOS_CENTERMOUSE
            ("WINDOW_Layout",  root),          # <-- canonical tag
        ])
        _log(f"  win={hex(win)}")
        if not win:
            _log("new_object returned NULL — window.class not loaded?")
            return (None, 0)

        _log("do_method WM_OPEN (two args, no trailing) ...")
        intuiwin = _amiga.do_method(win, _amiga.WM_OPEN)
        _log(f"  intuiwin={hex(intuiwin)}")
        if not intuiwin:
            _log("WM_OPEN returned 0 — dispose + fallback")
            _amiga.dispose_object(win)
            return (None, 0)
        _log("window is OPEN — waiting for input")
        return (win, intuiwin)
    except Exception as e:
        print(f"try_reaction: EXC {type(e).__name__}: {e}", flush=True)
        return (None, 0)


def main():
    win, intuiwin = try_reaction()
    if not win:
        print("reaction_form: ReAction path unavailable — using "
              "open_dialog form instead.", flush=True)
        result = fallback_dialog()
        if result is None:
            print("reaction_form: cancelled.", flush=True)
        else:
            print("reaction_form: values:", flush=True)
            for k, v in result.items():
                print(f"  {k:<8}= {v!r}", flush=True)
        return 0

    print(f"reaction_form: ReAction window @ {hex(intuiwin)} — "
          "use it.", flush=True)
    result = None
    while True:
        ev = _amiga.wait_message(intuiwin, 5.0)
        if ev is None:
            continue
        cls, code = ev["class"], ev["code"]
        if cls == _amiga.IDCMP_CLOSEWINDOW:
            break
        if cls == _amiga.IDCMP_VANILLAKEY and code == 27:
            break
        if cls == _amiga.IDCMP_GADGETUP:
            if code == ID_OK:
                result = "OK"; break
            if code == ID_CANCEL:
                result = "Cancel"; break

    _amiga.do_method(win, _amiga.WM_CLOSE)
    _amiga.dispose_object(win)
    print(f"reaction_form: closed ({result or 'no action'})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
