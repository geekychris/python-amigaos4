"""time.sleep works on OS4 PPC via the amiga_shim nanosleep→Delay path.

Guards against regression of the OSError [Errno 0] bug that hit us in
Phase 4: neither nanosleep nor clock_nanosleep was autoconf-detected,
so pysleep() fell through to select(0,NULL,NULL,NULL,&tv) which
bsdsocket.library rejects.  Now amiga_shim.h #defines HAVE_NANOSLEEP
and amiga_shim.c provides one via AmigaDOS Delay()."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
t = framework.new(__file__)

t.section("basic sleep")
for delay in (0.05, 0.2, 0.5, 1.0):
    t0 = time.monotonic()
    time.sleep(delay)
    elapsed = time.monotonic() - t0
    # Allow generous slack — Amiga Delay() has 50Hz (20ms) granularity
    # and QEMU can add variable latency.
    lo, hi = delay * 0.6, delay + 0.2
    t.check(lo <= elapsed <= hi,
             f"sleep({delay}) elapsed={elapsed:.3f}s in [{lo:.3f}, {hi:.3f}]")

t.section("zero and near-zero sleep")
t0 = time.monotonic()
time.sleep(0)
t.check((time.monotonic() - t0) < 0.05, "sleep(0) returns quickly")

t.section("monotonic non-decreasing")
prev = time.monotonic()
for _ in range(50):
    curr = time.monotonic()
    t.check(curr >= prev, "monotonic non-decreasing")
    prev = curr

t.run()
