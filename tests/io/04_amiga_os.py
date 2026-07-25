"""amiga.os.run — subprocess-style command execution.

Phase 4 sub-goal: verify the subprocess shim (which lands on os.system()
+ tempfile capture, since AmigaOS has no fork)."""
import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
_tests_root = os.path.dirname(_here)
sys.path.insert(0, _tests_root)
sys.path.insert(0, os.path.join(_tests_root, "amiga_bindings"))

import framework
t = framework.new(__file__)

from amiga import os as aos

t.section("run — simple echo")
r = aos.run("echo hello-amiga", capture_output=True, text=True)
t.check_eq(r.returncode, 0, "rc = 0")
t.check("hello-amiga" in r.stdout, "captured stdout")

t.section("run — list args get quoted")
r = aos.run(["echo", "hello world"], capture_output=True, text=True)
t.check_eq(r.returncode, 0, "list rc = 0")
t.check("hello world" in r.stdout, "captured quoted arg")

t.section("run — check=True")
try:
    aos.run("failnotacommand-xyz", check=True, capture_output=True)
    t.check(False, "check=True should have raised")
except aos.CalledProcessError as e:
    t.check(e.returncode != 0, "CalledProcessError has non-zero rc")
except BaseException as e:
    t.check(False, f"wrong exception: {type(e).__name__}")

t.section("call / check_call")
t.check_eq(aos.call("echo call"), 0, "call returns rc")
t.check_eq(aos.check_call("echo cc"), 0, "check_call OK")

t.section("check_output")
out = aos.check_output("echo ok-output", text=True)
t.check("ok-output" in out, "check_output returns stdout str")

t.section("Popen raises NotImplementedError")
try:
    aos.Popen("echo x")
    t.check(False, "Popen should raise")
except NotImplementedError:
    t.check(True, "Popen raised NotImplementedError")

t.run()
