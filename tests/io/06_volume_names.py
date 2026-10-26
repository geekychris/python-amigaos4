"""Paths that start with a volume name ("Ram Disk:", "Workbench:") work.

newlib only understands device names (RAM:, DH1:) and a few built-in
assigns, so amiga_shim.c rewrites any other NAME: to its device form
through AmigaDOS (DevNameFromLock).  Before that, a volume-name path
was turned into /NAME/path and every call on it failed with
FileNotFoundError, e.g. open("Workbench:S/Startup-Sequence") or a
script path from NameFromLock()."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
t = framework.new(__file__)

DEV = "RAM:pyvoltest"
VOL = "Ram Disk:pyvoltest"

t.section("setup through the device name")
os.makedirs(DEV, exist_ok=True)
with open(DEV + "/a.txt", "w") as f:
    f.write("written via RAM:")
t.check(os.path.isdir(DEV), "RAM:pyvoltest exists")

t.section("the same files through the volume name")
t.check(os.path.isdir(VOL), "isdir(Ram Disk:pyvoltest)")
t.check(os.path.exists(VOL + "/a.txt"), "exists(Ram Disk:pyvoltest/a.txt)")
with open(VOL + "/a.txt") as f:
    t.check_eq(f.read(), "written via RAM:", "read through the volume name")
t.check("a.txt" in os.listdir(VOL), "listdir(Ram Disk:pyvoltest)")
t.check_eq(os.stat(VOL + "/a.txt").st_size, 16, "stat size through the volume name")

t.section("writes through the volume name land on the device")
with open(VOL + "/b.txt", "w") as f:
    f.write("written via Ram Disk:")
with open(DEV + "/b.txt") as f:
    t.check_eq(f.read(), "written via Ram Disk:", "volume-name write visible on RAM:")
t.check(os.path.isdir("Ram Disk:"), "the volume root itself")

t.section("an unknown name fails cleanly, no requester")
t.check_raises(FileNotFoundError, os.stat, "NoSuchVolume_x9:file")

for n in ("a.txt", "b.txt"):
    os.remove(DEV + "/" + n)
os.rmdir(DEV)
t.run()
