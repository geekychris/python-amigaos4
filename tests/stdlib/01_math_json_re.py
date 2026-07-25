"""Pure-Python stdlib: math, json, re — all zero-syscall so should
just work once encodings imports."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("math")
import math
T.check(abs(math.sqrt(2) - 1.4142135623730951) < 1e-15, "sqrt")
T.check_eq(math.gcd(12, 18), 6, "gcd")
T.check_eq(math.factorial(10), 3628800, "factorial")
T.check(math.isclose(math.sin(math.pi), 0.0, abs_tol=1e-10), "sin(pi)")
T.check_eq(math.log(math.e), 1.0, "log(e)")
T.check_eq(math.pow(2, 10), 1024.0, "pow")
T.check(math.isnan(float("nan")), "isnan")
T.check(math.isinf(float("inf")), "isinf")

T.section("json")
import json
data = {"name": "amiga", "mb": 512, "flags": ["boot", "read"], "empty": None}
s = json.dumps(data, sort_keys=True)
T.check_eq(s, '{"empty": null, "flags": ["boot", "read"], "mb": 512, "name": "amiga"}',
          "dumps sort_keys")
back = json.loads(s)
T.check_eq(back, data, "roundtrip")

T.check_eq(json.loads("42"), 42, "int")
T.check_eq(json.loads("3.14"), 3.14, "float")
T.check_eq(json.loads("true"), True, "true")
T.check_eq(json.loads("null"), None, "null")
T.check_eq(json.loads('"hi"'), "hi", "string")
T.check_raises(json.JSONDecodeError, json.loads, "not-json")

T.section("re")
import re
m = re.match(r"(\w+):(\d+)", "port:8080")
T.check(m is not None, "match")
T.check_eq(m.group(1), "port", "group 1")
T.check_eq(m.group(2), "8080", "group 2")
T.check_eq(re.findall(r"\d+", "a1 b22 c333"), ["1", "22", "333"], "findall")
T.check_eq(re.sub(r"\s+", "-", " a  b\tc"), "-a-b-c", "sub")
T.check_eq(re.split(r"[,;]\s*", "a, b;c,d"), ["a", "b", "c", "d"], "split")

# named groups
m = re.match(r"(?P<vol>[A-Z][A-Z0-9]*):(?P<path>.*)", "DH1:lib/foo")
T.check_eq(m.group("vol"), "DH1", "named vol")
T.check_eq(m.group("path"), "lib/foo", "named path")

# non-greedy
T.check_eq(re.findall(r"<(.+?)>", "<a><b><c>"), ["a", "b", "c"], "non-greedy")

# ignore case
T.check(re.match(r"amiga", "AMIGA", re.I) is not None, "re.I")

T.run()
