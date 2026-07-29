"""Probe the amiga_bindings package.

Phase A implementations are wired for: amiga.dos.*, amiga.exec.MsgPort/
Signal/Wait/FindTask/AvailMem, amiga.intuition.* (in sim mode).

Anything still stubbed with NotImplementedYet is skipped here — those
lines flip to check() calls as Phase B/C land."""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
_tests_root = os.path.dirname(_here)
sys.path.insert(0, _tests_root)                            # for `framework`
sys.path.insert(0, os.path.join(_tests_root, "amiga_bindings"))  # for `amiga`

try:
    from amiga import capabilities, NotImplementedYet
    import amiga.dos as dos
    import amiga.exec as ex
    import amiga.intuition as intu
except ImportError as e:
    print(f"SKIP: amiga bindings not installed on this Python:{e}")
    sys.exit(0)

import framework
T = framework.new(__file__)


T.section("capabilities")
caps = capabilities()
T.check(isinstance(caps, dict), "capabilities returns dict")
for name, (ok, why) in caps.items():
    T.check(isinstance(ok, bool), f"cap {name} has bool status")


T.section("amiga.dos — real Phase A implementations")
vols = dos.Info()
T.check(len(vols) > 0, "Info returns at least one volume")
dh1_hits = [v for v in vols if v.unit.upper() == "DH1"]
T.check(len(dh1_hits) >= 1, "DH1 volume present")

assigns = dos.Assign()
T.check(isinstance(assigns, dict), "Assign() returns dict")
T.check(len(assigns) > 0, "Assign() has at least one entry")

info = dos.Examine("python3")
T.check(info.size > 1_000_000, "python-os4 binary >1MB")
T.check(info.is_dir is False, "python-os4 is a file, not dir")

rc, out = dos.Execute("echo test-execute", capture=True)
T.check_eq(rc, 0, "Execute rc")
T.check("test-execute" in out, "Execute captured stdout")


T.section("amiga.exec — MsgPort round-trip")
port = ex.CreateMsgPort("_test_port", public=True)
found = ex.FindPort("_test_port")
T.check(found is port, "FindPort returns our public port")

reply_port = ex.CreateMsgPort("_test_reply")
ex.PutMsg(port, "ping", reply_port=reply_port)
m = ex.WaitPort(port, timeout=1.0)
T.check(m is not None, "WaitPort delivered a message")
if m is not None:
    T.check_eq(m.data, "ping", "message payload")
    T.check_eq(m.reply_port, reply_port, "reply_port carried")
    m.reply(response="pong")
    r = ex.WaitPort(reply_port, timeout=1.0)
    T.check(r is not None, "reply delivered")
    if r is not None:
        T.check_eq(r.data, "pong", "reply payload")

ex.DeleteMsgPort(port)
ex.DeleteMsgPort(reply_port)


T.section("amiga.exec — Signal/Wait")
bit, sig = ex.AllocSignal()
T.check(isinstance(bit, int), "AllocSignal returns int bit")
T.check(ex.Wait(sig, timeout=0.1) is False, "Wait times out with no signal")
ex.Signal(sig)
T.check(ex.Wait(sig, timeout=0.1) is True, "Wait fires after Signal")


T.section("amiga.exec — introspection")
me = ex.FindTask()
T.check(me is not None, "FindTask(None) returns current task")
if me is not None:
    # With Phase 6 native backend, this returns the real CLI task name
    # (e.g. "Background CLI").  Without native, our fallback synthesises
    # "python".  Just check it's a non-empty string.
    T.check(isinstance(me.name, str) and len(me.name) > 0,
             f"task name is non-empty str (got {me.name!r})")


T.section("amiga.intuition — sim mode round-trip")
# In sim mode (default), OpenWindow/close should complete without raising.
w = intu.OpenWindow(title="TestWin", left=10, top=10, width=200, height=100,
                     idcmp=intu.IDCMP_CLOSEWINDOW | intu.IDCMP_VANILLAKEY)
T.check(w.id >= 1, "Window id assigned")
T.check(w.width == 200, "Window width")

# Feed a synthetic event; drain it back.
evt = intu.IntuiEvent(kind="key", gadget_id=None, code=65,
                      qualifier=0, mouse_x=0, mouse_y=0)
w.post(evt)
T.check(w.wait(timeout=1.0) is True, "wait sees the posted event")
drained = w.events()
T.check_eq(len(drained), 1, "events drained exactly one")
T.check_eq(drained[0].code, 65, "event payload roundtrip")
w.close()

screens = intu.list_screens()
T.check(len(screens) >= 1, "list_screens returns Workbench in sim mode")


T.section("still-stubbed pieces (Phase B/C)")
T.check_raises(NotImplementedYet, ex.OpenLibrary, "dos.library")
T.check_raises(NotImplementedYet, ex.list_libraries)
T.check_raises(NotImplementedYet, intu.screenshot)


T.run()
