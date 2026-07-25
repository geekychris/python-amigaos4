"""Basic file open/read/write/seek — the shimmed-newlib path.
Uses RAM: for a truly-writable filesystem."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

RAM = "RAM:python_iotest"
try:
    os.mkdir(RAM)
except FileExistsError:
    pass
except OSError as e:
    T.check(False, f"mkdir RAM setup: {e}")

T.section("write + read text")
p = f"{RAM}/hello.txt"
with open(p, "w") as f:
    f.write("hello amiga\nsecond line\n")

with open(p, "r") as f:
    content = f.read()
T.check_eq(content, "hello amiga\nsecond line\n", "text roundtrip")

T.section("read lines")
with open(p) as f:
    lines = f.readlines()
T.check_eq(lines, ["hello amiga\n", "second line\n"], "readlines")

T.section("write + read bytes")
bp = f"{RAM}/bin.dat"
data = bytes(range(256))
with open(bp, "wb") as f:
    f.write(data)
with open(bp, "rb") as f:
    back = f.read()
T.check_eq(back, data, "binary roundtrip")
T.check_eq(len(back), 256, "byte length")

T.section("seek + tell")
with open(bp, "rb") as f:
    f.seek(100)
    T.check_eq(f.tell(), 100, "tell after seek")
    b = f.read(1)
    T.check_eq(b, bytes([100]), "read byte at 100")
    f.seek(0, 2)  # SEEK_END
    T.check_eq(f.tell(), 256, "seek to end")

T.section("open modes")
ap = f"{RAM}/append.txt"
with open(ap, "w") as f:  f.write("A")
with open(ap, "a") as f:  f.write("B")
with open(ap, "a") as f:  f.write("C")
with open(ap) as f:       s = f.read()
T.check_eq(s, "ABC", "append")

T.section("os.stat")
st = os.stat(bp)
T.check_eq(st.st_size, 256, "st_size")
T.check(st.st_mtime > 0, "st_mtime > 0")

T.section("os.listdir")
files = set(os.listdir(RAM))
T.check("hello.txt" in files, "listdir sees hello.txt")
T.check("bin.dat" in files, "listdir sees bin.dat")
T.check("append.txt" in files, "listdir sees append.txt")

T.section("os.path")
T.check(os.path.isfile(p), "isfile")
T.check(os.path.isdir(RAM), "isdir")
T.check(not os.path.isfile(RAM), "!isfile on dir")
T.check_eq(os.path.getsize(bp), 256, "getsize")

T.section("os.remove + rmdir")
os.remove(p)
os.remove(bp)
os.remove(ap)
T.check(not os.path.exists(p), "removed")
os.rmdir(RAM)
T.check(not os.path.exists(RAM), "rmdir")

T.run()
