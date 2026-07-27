"""reaction_form.py — a working form with visible widgets.

Opens a real Intuition window containing labeled string fields and
OK/Cancel buttons via _amiga.open_dialog. Every field is editable;
OK returns the collected values, Cancel returns None.

For the BOOPSI/ReAction path (button.gadget + layout.gadget +
window.class + WM_OPEN), see boopsi_probe.py. Full window.class
integration needs a multi-value LAYOUT_AddChild helper we haven't
built yet — the current BOOPSI surface can allocate the objects
(_amiga.new_object works) but can't yet render them into a
resizable ReAction window from Python alone.

Run:
    DH1:python-os4 DH1:pytests/examples/reaction_form.py
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga


def prompt(title, fields, ok_label="OK", cancel_label="Cancel"):
    h = _amiga.open_dialog(
        title=title, fields=fields,
        ok_label=ok_label, cancel_label=cancel_label,
        left=140, top=100,
    )
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


def main():
    print("reaction_form: opening person-entry dialog...", flush=True)
    result = prompt(
        "New person",
        [("Name",   "",             40),
         ("Age",    "30",            5),
         ("Email",  "you@example.com", 60),
         ("Notes",  "",            120)],
        ok_label="Save", cancel_label="Cancel",
    )
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
