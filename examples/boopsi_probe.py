"""boopsi_probe.py — self-test of the BOOPSI surface in _amiga.

Not a rendered UI — this exercises the C entry points to confirm
they exist and behave. Prints one PASS/FAIL line per check. Useful
after a python-os4 rebuild to verify BOOPSI didn't regress.

If you want *visible* BOOPSI widgets, the current state is:
    - _amiga.new_object("button.gadget", ...) → returns a real
      allocated Gadget * we can dispose_object cleanly.
    - _amiga.do_method(win_obj, WM_OPEN) → currently returns 0
      because window.class needs children attached via
      LAYOUT_AddChild in the initial NewObject tag list, not via
      later set_attrs (dict-key uniqueness prevents that from Python
      until we add a multi-value tag helper).
    - Getting a fully-rendered ReAction window from Python needs
      one more _amiga entry point + a bigger reaction_form rewrite.
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga


def check(name, cond, detail=""):
    tag = "PASS" if cond else "FAIL"
    line = f"{tag}: {name}"
    if detail:
        line += f"   ({detail})"
    print(line, flush=True)
    return cond


def main():
    # 1. New/dispose on a simple leaf class.
    try:
        b = _amiga.new_object("button.gadget", {
            "GA_ID":     42,
            "GA_Text":   "Test",
            "GA_Left":   10, "GA_Top": 10,
            "GA_Width": 100, "GA_Height": 20,
            "GA_RelVerify": True,
        })
        check("button.gadget alloc", b != 0, f"handle={hex(b)}")
        _amiga.dispose_object(b)
        check("button.gadget dispose", True)
    except Exception as e:
        check("button.gadget alloc", False, str(e))

    # 2. set_attrs on a live object.
    try:
        b = _amiga.new_object("button.gadget", {
            "GA_ID": 1, "GA_Text": "hi", "GA_RelVerify": True,
        })
        _amiga.set_attrs(b, {"GA_Disabled": True})
        v = _amiga.get_attr(b, "GA_Disabled")
        check("set_attrs + get_attr roundtrip", v == 1,
              f"got {v} expected 1")
        _amiga.dispose_object(b)
    except Exception as e:
        check("set_attrs roundtrip", False, str(e))

    # 3. do_method presence check.
    have_dm = hasattr(_amiga, "do_method")
    check("do_method exposed", have_dm)

    # 4. Menu-strip presence check.
    check("set_menu_strip exposed", hasattr(_amiga, "set_menu_strip"))
    check("menu_pick_decode exposed", hasattr(_amiga, "menu_pick_decode"))

    # 5. Window-class method constants exposed?
    check("WM_OPEN constant",  hasattr(_amiga, "WM_OPEN"))
    check("WM_CLOSE constant", hasattr(_amiga, "WM_CLOSE"))

    # 6. layout.gadget alloc — the composition primitive.
    try:
        lay = _amiga.new_object("layout.gadget", {
            "LAYOUT_Orientation": 1,   # vertical
        })
        check("layout.gadget alloc", lay != 0, f"handle={hex(lay)}")
        _amiga.dispose_object(lay)
    except Exception as e:
        check("layout.gadget alloc", False, str(e))

    # 7. listbrowser.gadget alloc.
    try:
        lb = _amiga.new_object("listbrowser.gadget", {
            "GA_ID": 100, "GA_Left": 0, "GA_Top": 0,
            "GA_Width": 200, "GA_Height": 100,
        })
        check("listbrowser.gadget alloc", lb != 0, f"handle={hex(lb)}")
        _amiga.dispose_object(lb)
    except Exception as e:
        check("listbrowser.gadget alloc", False, str(e))

    print("\nboopsi_probe: done.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
