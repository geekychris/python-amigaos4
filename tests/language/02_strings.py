"""String operations, f-strings, unicode basics."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
t = framework.new(__file__)

t.section("basic")
s = "hello, amiga"
t.check_eq(len(s), 12, "len")
t.check_eq(s.upper(), "HELLO, AMIGA", "upper")
t.check_eq(s.split(", "), ["hello", "amiga"], "split")
t.check_eq("-".join(["a", "b", "c"]), "a-b-c", "join")
t.check(s.startswith("hello"), "startswith")
t.check(s.endswith("amiga"), "endswith")
t.check_eq(s.replace("amiga", "OS4"), "hello, OS4", "replace")

t.section("slicing")
t.check_eq(s[0], "h", "index 0")
t.check_eq(s[-1], "a", "index -1")
t.check_eq(s[0:5], "hello", "slice 0:5")
t.check_eq(s[::-1], "agima ,olleh", "reverse")
t.check_eq(s[::2], "hlo mg", "step 2")

t.section("f-strings")
n, v = 42, 3.14
t.check_eq(f"n={n} v={v}", "n=42 v=3.14", "basic")
t.check_eq(f"{n:04d}", "0042", "zero pad")
t.check_eq(f"{v:.2f}", "3.14", "float format")
t.check_eq(f"{n!r}", "42", "!r")
t.check_eq(f"{'amiga':>10}", "     amiga", "right align")
t.check_eq(f"{n=}", "n=42", "debug =")

t.section("methods")
t.check_eq("  hi  ".strip(), "hi", "strip")
t.check_eq("hello".find("ll"), 2, "find hit")
t.check_eq("hello".find("zz"), -1, "find miss")
t.check_eq("abc".zfill(6), "000abc", "zfill")
t.check_eq("A,B,,C".split(","), ["A", "B", "", "C"], "split empty parts")

t.section("unicode")
t.check_eq(ord("A"), 65, "ord")
t.check_eq(chr(65), "A", "chr")
t.check_eq(len("café"), 4, "unicode len")
t.check_eq("café".encode("utf-8"), b"caf\xc3\xa9", "utf-8 encode")
t.check_eq(b"caf\xc3\xa9".decode("utf-8"), "café", "utf-8 decode")

t.section("bytes")
t.check_eq(b"abc"[0], 97, "bytes index -> int")
t.check_eq(bytes([72, 105]), b"Hi", "from list")
t.check_eq(bytes.fromhex("deadbeef"), b"\xde\xad\xbe\xef", "fromhex")
t.check_eq(b"\xde\xad".hex(), "dead", "hex")

t.run()
