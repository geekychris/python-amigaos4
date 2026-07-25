"""Probe the amiga_bindings package — every stub should raise
NotImplementedYet with a phase code. Once real implementations
land, this file's `SKIP:` lines flip to `PASS:`."""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
_tests_root = os.path.dirname(_here)
sys.path.insert(0, _tests_root)                            # for `framework`
sys.path.insert(0, os.path.join(_tests_root, "amiga_bindings"))  # for `amiga` package
try:
    from amiga import capabilities, NotImplementedYet
    import amiga.bridge as br
    import amiga.dos as dos
    import amiga.intuition as intu
    import amiga.exec as ex
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

T.section("stub coverage")
T.check_raises(NotImplementedYet, br.log, "info", "test")
T.check_raises(NotImplementedYet, br.exec, "list")
T.check_raises(NotImplementedYet, dos.Info, "DH1:")
T.check_raises(NotImplementedYet, dos.MakeDir, "RAM:x")
T.check_raises(NotImplementedYet, intu.list_screens)
T.check_raises(NotImplementedYet, ex.FindTask)
T.check_raises(NotImplementedYet, ex.AvailMem)

T.section("stub error carries phase code")
try:
    br.log("info", "test")
except NotImplementedYet as e:
    T.check(e.phase in ("A", "B", "C", "A+4", "B/C", "3", "4", "5", "6"),
            f"phase code: {e.phase!r}")

T.run()
