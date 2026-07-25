"""Native Intuition entry points on the _amiga module (Phase 6.5).

Verifies open_window / draw_text / clear_window / get_message /
wait_message / close_window against a real Workbench screen.
Skipped if the _amiga module was built without the intuition
symbols."""
import sys, os, time
_here = os.path.dirname(os.path.abspath(__file__))
_tests_root = os.path.dirname(_here)
sys.path.insert(0, _tests_root)
sys.path.insert(0, os.path.join(_tests_root, "amiga_bindings"))

import framework
t = framework.new(__file__)

try:
    import _amiga
except ImportError:
    t.skip("_amiga native module not present")

if not hasattr(_amiga, "open_window"):
    t.skip("_amiga present but built without Intuition entry points")

# Constants exposed?
t.section("constants exposed")
for name in ("IDCMP_CLOSEWINDOW", "IDCMP_VANILLAKEY", "IDCMP_NEWSIZE",
             "IDCMP_REFRESHWINDOW", "WFLG_SIZEGADGET", "WFLG_DRAGBAR",
             "WFLG_CLOSEGADGET"):
    t.check(hasattr(_amiga, name), f"constant {name} present")


t.section("open + geometry + close")
handle = _amiga.open_window(
    title="_amiga self-test",
    left=50, top=50, width=300, height=100,
    idcmp=_amiga.IDCMP_CLOSEWINDOW,
)
t.check(handle > 0, "open_window returned non-zero handle")

geom = _amiga.window_geom(handle)
t.check(isinstance(geom, dict), "window_geom is dict")
t.check(geom["inner_width"] == 300, f"inner_width={geom['inner_width']}")
t.check(geom["inner_height"] == 100, f"inner_height={geom['inner_height']}")
t.check(geom["border_left"] > 0, "has left border")
t.check(geom["border_top"] > 15, "has title bar")


t.section("draw + clear")
_amiga.clear_window(handle, 0)
_amiga.draw_text(handle, 10, 20, "self-test drawing", 1)
_amiga.draw_text(handle, 10, 40, "line 2", 2)
_amiga.draw_text(handle, 10, 60, "line 3", 3)
# We can't visually verify the pixels without a screenshot, but the
# calls should not crash and should return None.
t.check(True, "draw/clear complete without exception")


t.section("non-blocking message drain")
# Fresh window shouldn't have any messages queued.
msg = _amiga.get_message(handle)
# May or may not be None depending on activate events — just check
# the return shape.
if msg is not None:
    t.check(isinstance(msg, dict), "get_message returns dict when present")
    t.check("class" in msg, "message has class")


t.section("wait_message timeout")
t0 = time.monotonic()
msg = _amiga.wait_message(handle, 0.3)
elapsed = time.monotonic() - t0
# Timeout ~300ms; allow slop for Delay granularity.
t.check(elapsed >= 0.25, f"waited at least 250ms (was {elapsed:.3f}s)")
t.check(elapsed < 1.5, f"didn't wait much longer than requested")


t.section("active_window")
active = _amiga.active_window()
# Our test window may or may not be active depending on user focus;
# just check the call returns an int (or None) without error.
t.check(active is None or isinstance(active, int),
         "active_window returns int|None")


t.section("close")
_amiga.close_window(handle)
# Second close should be safe (handle is stale but code guards).
_amiga.close_window(handle)
t.check(True, "close_window handled twice without crash")


t.run()
