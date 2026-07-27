"""reaction_form.py — real ReAction window with layout.gadget.

Web-search revealed the two things my earlier attempts had wrong:
  1. IDoMethod(obj, WM_OPEN, NULL) — NULL arg required. My earlier
     code sent just WM_OPEN which made window.class read garbage.
  2. window.class + layout.gadget class-lookup works via string
     name too, but attaches children more reliably when
     LAYOUT_AddChild entries live in the initial NewObject tag list
     — which needs new_object_multi (already in _amiga).

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
        return (None, 0)

    try:
        name = _amiga.new_object("string.gadget", {
            "GA_ID": ID_NAME, "STRINGA_MaxChars": 40,
            "STRINGA_TextVal": "", "LAYOUT_Label": "Name:",
        })
        age = _amiga.new_object("integer.gadget", {
            "GA_ID": ID_AGE, "INTEGER_Number": 30,
            "INTEGER_Minimum": 0, "INTEGER_Maximum": 200,
            "LAYOUT_Label": "Age:",
        })
        email = _amiga.new_object("string.gadget", {
            "GA_ID": ID_EMAIL, "STRINGA_MaxChars": 60,
            "STRINGA_TextVal": "you@example.com",
            "LAYOUT_Label": "Email:",
        })
        notes = _amiga.new_object("string.gadget", {
            "GA_ID": ID_NOTES, "STRINGA_MaxChars": 120,
            "STRINGA_TextVal": "", "LAYOUT_Label": "Notes:",
        })
        ok = _amiga.new_object("button.gadget", {
            "GA_ID": ID_OK, "GA_Text": "OK", "GA_RelVerify": True,
        })
        cancel = _amiga.new_object("button.gadget", {
            "GA_ID": ID_CANCEL, "GA_Text": "Cancel", "GA_RelVerify": True,
        })

        button_row = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 0),
            ("LAYOUT_AddChild", ok),
            ("LAYOUT_AddChild", cancel),
        ])
        root = _amiga.new_object_multi("layout.gadget", [
            ("LAYOUT_Orientation", 1),
            ("LAYOUT_SpaceOuter", True),
            ("LAYOUT_SpaceInner", True),
            ("LAYOUT_AddChild", name),
            ("LAYOUT_AddChild", age),
            ("LAYOUT_AddChild", email),
            ("LAYOUT_AddChild", notes),
            ("LAYOUT_AddChild", button_row),
        ])
        win = _amiga.new_object("window.class", {
            "WA_Title":         "Python ReAction form",
            "WA_DragBar":       True,
            "WA_CloseGadget":   True,
            "WA_DepthGadget":   True,
            "WA_SizeGadget":    True,
            "WA_Activate":      True,
            "WA_IDCMP":         (_amiga.IDCMP_CLOSEWINDOW
                                 | _amiga.IDCMP_GADGETUP
                                 | _amiga.IDCMP_VANILLAKEY),
            "WINDOW_Position":  0,               # WPOS_CENTERSCREEN
            "WINDOW_ParentGroup": root,
        })
        # The critical fix — pass NULL as the WM_OPEN payload's
        # second word.  Without it window.class reads stack garbage.
        intuiwin = _amiga.do_method(win, _amiga.WM_OPEN, 0)
        if not intuiwin:
            print("try_reaction: WM_OPEN still returned 0.",
                  flush=True)
            _amiga.dispose_object(win)
            return (None, 0)
        return (win, intuiwin)
    except Exception as e:
        print(f"try_reaction: {type(e).__name__}: {e}", flush=True)
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

    _amiga.do_method(win, _amiga.WM_CLOSE, 0)
    _amiga.dispose_object(win)
    print(f"reaction_form: closed ({result or 'no action'})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
