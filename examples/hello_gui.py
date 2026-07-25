"""hello_gui — Intuition window + IDCMP event loop (paradigm demo).

Runs in simulation mode today (AMIGA_INTUITION_SIM=1 default) — every
OpenWindow / draw_text / event call prints an `[intu.sim]` line so
you can see the intended UI flow.  When Phase B/C wires ctypes onto
intuition.library, THIS SAME SCRIPT will open a real Workbench window.

The EasyRequest at the top DOES pop a real Intuition requester today —
it shells out to `RequestChoice`, a stock OS4 CLI tool.
"""
import sys, os
sys.path.insert(0, "DH1:pytests/amiga_bindings")

from amiga import intuition as intu
from amiga.exec import PutMsg   # for feeding synthetic events in sim mode


def main():
    # -- Real Intuition today: EasyRequest via RequestChoice ---------------
    # NOTE: pops a modal Intuition requester on the Workbench screen.
    #   Pass 'req' on the command line to enable (default: skip so this
    #   script runs cleanly in an automated harness).
    if "req" in sys.argv:
        print("=== EasyRequest demo (real Intuition popup) ===")
        choice = intu.EasyRequest(
            title="Python OS4 demo",
            body="This dialog comes from Python via RequestChoice.\\nContinue?",
            buttons=("Continue", "Skip", "Abort"))
        print(f"user picked button index: {choice}")
    else:
        print("=== EasyRequest skipped (pass 'req' to enable) ===")

    # -- Simulated window / event loop (Phase A shape) ---------------------
    print("\n=== Simulated OpenWindow + event loop ===")
    win = intu.OpenWindow(
        title="Hello, Amiga",
        left=100, top=80,
        width=400, height=300,
        idcmp=intu.IDCMP_CLOSEWINDOW
              | intu.IDCMP_VANILLAKEY
              | intu.IDCMP_MOUSEBUTTONS
              | intu.IDCMP_NEWSIZE,
    )

    win.draw_text(10, 20, "Hello, Amiga.")
    win.draw_text(10, 40, "Press ESC to quit.")

    # In real use, Intuition sends events onto win._port asynchronously.
    # In sim mode we push a few synthetic events so the event loop shows
    # off the drain pattern.
    win.post(intu.IntuiEvent(kind="key", gadget_id=None, code=ord('a'),
                              qualifier=0, mouse_x=0, mouse_y=0))
    win.post(intu.IntuiEvent(kind="mouseclick", gadget_id=None, code=1,
                              qualifier=0, mouse_x=42, mouse_y=64))
    win.post(intu.IntuiEvent(kind="key", gadget_id=None, code=27,  # ESC
                              qualifier=0, mouse_x=0, mouse_y=0))
    win.post(intu.IntuiEvent(kind="close", gadget_id=None, code=0,
                              qualifier=0, mouse_x=0, mouse_y=0))

    print("\n[event loop starts]")
    running = True
    while running:
        win.wait(timeout=1.0)
        for e in win.events():
            print(f"  event: {e}")
            if e.kind == "close":
                print("  -> user closed window")
                running = False
            elif e.kind == "key" and e.code == 27:
                print("  -> ESC, quitting")
                running = False
            elif e.kind == "key":
                print(f"  -> key char {chr(e.code)!r}")
            elif e.kind == "mouseclick":
                print(f"  -> click at ({e.mouse_x},{e.mouse_y})")

    win.close()
    print("\nhello_gui: OK")


if __name__ == "__main__":
    main()
