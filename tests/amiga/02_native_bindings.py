"""Native _amiga module — verifies Phase 6 direct-to-IExec/IDOS calls.

Everything here uses `_amiga.*` directly (bypassing amiga_bindings
wrappers) to prove the C module works.  Then it re-runs amiga.exec
introspection to confirm the wrappers now use the native path."""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
_tests_root = os.path.dirname(_here)
sys.path.insert(0, _tests_root)
sys.path.insert(0, os.path.join(_tests_root, "amiga_bindings"))

import framework
t = framework.new(__file__)

t.section("_amiga module presence")
try:
    import _amiga
    HAVE = True
except ImportError:
    HAVE = False
    t.skip("_amiga builtin missing — this Python was built without Phase 6")

t.check(HAVE, "_amiga imports")


t.section("version / metadata")
name, version, phase = _amiga.version()
t.check(isinstance(name, str), "version[0] is str")
t.check("phase" in phase, "phase string mentions 'phase'")


t.section("memory query")
mem = _amiga.avail_mem_summary()
t.check(isinstance(mem, dict), "avail_mem_summary is dict")
for key in ("any", "public", "chip", "fast", "largest"):
    t.check(key in mem, f"key {key} present")
t.check(mem["any"] > 1_000_000, "any memory > 1MB (sanity)")


t.section("task enumeration")
me = _amiga.find_task()
t.check(me is not None, "find_task() returns current task")
if me is not None:
    tname, tpri, taddr = me
    t.check(isinstance(tname, str), "task name is str")
    t.check(taddr > 0, "task address non-zero")

tasks = _amiga.list_tasks()
t.check(len(tasks) > 5, "system has >5 tasks (sanity)")
# every entry is (name, priority, state)
for tn, pri, st in tasks[:5]:
    t.check(isinstance(tn, str), f"task name {tn!r} is str")
    t.check(st in ("Ready", "Wait"), f"state {st} is Ready|Wait")


t.section("library enumeration")
libs = _amiga.list_libraries()
t.check(len(libs) > 3, "system has >3 libraries")
lib_names = [l[0] for l in libs]
t.check(any("exec" in n.lower() or "newlib" in n.lower() or "dos" in n.lower()
             for n in lib_names),
        "found a core system library")


t.section("public MsgPort enumeration")
ports = _amiga.list_ports()
t.check(len(ports) > 0, "system has at least one public port")
t.check("WORKBENCH" in ports, "WORKBENCH port present")


t.section("Info() on a volume")
info = _amiga.volume_info("DH1:")
t.check(info is not None, "volume_info DH1: succeeds")
t.check(info["num_blocks"] > 0, "volume has blocks")
t.check(info["bytes_per_block"] in (512, 1024, 2048, 4096),
        f"bytes_per_block sane: {info['bytes_per_block']}")


t.section("amiga.exec wrappers flip to native")
import amiga.exec as ex
t.check(ex.HAS_NATIVE, "amiga.exec detected _amiga at import time")
me2 = ex.FindTask()
t.check(me2 is not None, "FindTask() via wrapper still works")

# list_tasks via wrapper should match the raw _amiga count.
ex_tasks = ex.list_tasks()
t.check(len(ex_tasks) >= len(tasks) - 5, "wrapper task count roughly matches native")


t.section("MEMF_* constants exported")
for name in ("MEMF_ANY", "MEMF_PUBLIC", "MEMF_CHIP", "MEMF_FAST"):
    t.check(hasattr(_amiga, name), f"MEMF constant {name} exposed")


t.run()
