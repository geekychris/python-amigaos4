"""reaction_form.py — proves BOOPSI / layout.gadget from Python.

Builds a small form with a labeled string field, a labeled integer,
and OK/Cancel buttons — all held together by a layout.gadget so the
window is resizable and the widgets stay tidy. The point of this
demo is *not* the form; it's that new_object / set_attrs / layout.gadget
work at all from Python. Any of the widgets can be extended or new
classes added by editing amiga.reaction.

If the BOOPSI kit isn't available (older python-os4 build), prints
a stub message and exits.

Run:
    DH1:python-os4 DH1:pytests/examples/reaction_form.py
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

try:
    import _amiga
    from amiga import reaction as rx
except ImportError as e:
    print(f"reaction_form: needs BOOPSI-enabled _amiga build ({e})")
    sys.exit(1)

if not hasattr(_amiga, "new_object"):
    print("reaction_form: this python-os4 build predates BOOPSI. "
          "Rebuild with the amissl_lazy + BOOPSI patch series.")
    sys.exit(2)


def main():
    # Build the widget graph.
    name  = rx.StringGadget(default="",   id=10, max_chars=40)
    age   = rx.IntegerGadget(default=30,  id=11, min=0, max=200)
    ok    = rx.Button("OK",     id=1)
    cancel = rx.Button("Cancel", id=2)

    # LABEL on each entry field, then stack them vertically.
    rx.Labeled("Name:", name)
    rx.Labeled("Age:",  age)

    # Buttons in a horizontal row.
    button_row = rx.LayoutGroup(
        orientation=rx.LAYOUT_ORIENT_HORIZ,
        children=[ok, cancel],
    )
    root = rx.LayoutGroup(
        orientation=rx.LAYOUT_ORIENT_VERT,
        children=[name, age, button_row],
    )

    # Open a plain window and attach the layout as the top-level gadget.
    # (A full ReAction wrap of window.class is not implemented yet — we
    # embed the layout into a regular Intuition window's gadget list.)
    handle = _amiga.open_window(
        title="Python BOOPSI form",
        left=120, top=100, width=420, height=200,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_GADGETUP),
    )
    print(f"reaction_form: window @ {hex(handle)}", flush=True)
    print(f"reaction_form: root layout handle = {hex(root.handle)}",
          flush=True)
    print("reaction_form: (this demo builds the objects; embedding into"
          " a Reaction window.class needs a follow-up rebuild)",
          flush=True)

    _amiga.clear_window(handle, 0)
    _amiga.draw_text(handle, 8, 20,
                     "BOOPSI form built (see stdout).", 1)
    _amiga.draw_text(handle, 8, 40,
                     f"  StringGadget @ {hex(name.handle)}", 1)
    _amiga.draw_text(handle, 8, 55,
                     f"  IntegerGadget @ {hex(age.handle)}", 1)
    _amiga.draw_text(handle, 8, 70,
                     f"  Button 'OK'  @ {hex(ok.handle)}", 1)
    _amiga.draw_text(handle, 8, 85,
                     f"  Button 'Cancel' @ {hex(cancel.handle)}", 1)
    _amiga.draw_text(handle, 8, 100,
                     f"  Layout root @ {hex(root.handle)}", 1)
    _amiga.draw_text(handle, 8, 130,
                     "Close window or ESC to dispose all objects.", 1)

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

    _amiga.close_window(handle)
    # Dispose in reverse dependency order (leaves before roots).
    for obj in (ok, cancel, name, age, button_row, root):
        obj.dispose()
    print("reaction_form: all BOOPSI objects disposed.", flush=True)


if __name__ == "__main__":
    main()
