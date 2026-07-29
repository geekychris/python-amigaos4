"""listbrowser_demo.py — instantiate a listbrowser.gadget via BOOPSI.

Demonstrates that _amiga.new_object("listbrowser.gadget", ...) succeeds
and can be attached to a window. Building a full column-headed sortable
list is a bigger undertaking (needs a live Exec-style List of Node
records, done via NewLBNode() from the listbrowser class; that surface
still needs to be added to amiga.reaction). This demo confirms the
object-model wiring is sound.

Run:
    python3 python3:examples/listbrowser_demo.py
"""
import sys, os
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

try:
    import _amiga
except ImportError:
    print("listbrowser_demo: needs _amiga native module")
    sys.exit(1)

if not hasattr(_amiga, "new_object"):
    print("listbrowser_demo: this python-os4 build predates BOOPSI. "
          "Rebuild with the BOOPSI patch series to get new_object.")
    sys.exit(2)


def main():
    handle = _amiga.open_window(
        title="Python listbrowser test",
        left=100, top=100, width=400, height=280,
        idcmp=_amiga.IDCMP_CLOSEWINDOW | _amiga.IDCMP_VANILLAKEY,
    )
    print(f"listbrowser_demo: window @ {hex(handle)}", flush=True)

    try:
        # Instantiate the listbrowser.gadget class.
        lb = _amiga.new_object("listbrowser.gadget", {
            "GA_ID":     100,
            "GA_Left":   10,
            "GA_Top":    30,
            "GA_Width":  380,
            "GA_Height": 220,
        })
        print(f"listbrowser_demo: object @ {hex(lb)}", flush=True)

        _amiga.clear_window(handle, 0)
        _amiga.draw_text(handle, 8, 15,
                         "listbrowser.gadget instantiated:", 1)
        _amiga.draw_text(handle, 8, 30,
                         f"  handle = {hex(lb)}", 1)
        _amiga.draw_text(handle, 8, 50,
                         "Adding rows needs the NewLBNode helper,", 1)
        _amiga.draw_text(handle, 8, 65,
                         "which is TODO for amiga.reaction.", 1)
        _amiga.draw_text(handle, 8, 85,
                         "ESC or close to quit.", 1)

        while True:
            ev = _amiga.wait_message(handle, 5.0)
            if ev is None:
                continue
            if ev["class"] == _amiga.IDCMP_CLOSEWINDOW:
                break
            if ev["class"] == _amiga.IDCMP_VANILLAKEY and ev["code"] == 27:
                break

        _amiga.dispose_object(lb)
        print("listbrowser_demo: object disposed.", flush=True)
    finally:
        _amiga.close_window(handle)


if __name__ == "__main__":
    main()
