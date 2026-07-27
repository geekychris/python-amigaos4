"""reaction_form.py — a working editable form via _amiga.open_dialog.

Opens a real Intuition window with labeled string fields you can
edit — the labels line up with their gadgets now that _amigamodule.c
draws them in the same coordinate frame as the gadget positions.

The full BOOPSI/ReAction path (window.class + WM_OPEN with a
layout.gadget root) still needs work — window.class on OS4 wants
OpenClass()-ed class pointers or a properly-scoped screen context
before WM_OPEN succeeds. See boopsi_probe.py to confirm the object
model itself works (NewObject / SetAttrs / DoMethod all present +
functional against button.gadget / string.gadget / layout.gadget /
listbrowser.gadget).

Run:
    DH1:python-os4 DH1:pytests/examples/reaction_form.py
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga


def main():
    print("reaction_form: opening person-entry dialog...", flush=True)
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
        result = _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)

    if result is None:
        print("reaction_form: cancelled.", flush=True)
        return 0
    print("reaction_form: values collected:", flush=True)
    for label, val in result.items():
        print(f"  {label:<8}= {val!r}", flush=True)
    print("reaction_form: done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
