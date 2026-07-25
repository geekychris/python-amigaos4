"""Sequence + mapping + set core operations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("list")
xs = [1, 2, 3, 4, 5]
T.check_eq(len(xs), 5, "len")
T.check_eq(xs[2], 3, "index")
T.check_eq(xs[-2:], [4, 5], "slice tail")
xs.append(6)
T.check_eq(xs, [1, 2, 3, 4, 5, 6], "append")
xs.insert(0, 0)
T.check_eq(xs[0], 0, "insert front")
T.check_eq(xs.pop(), 6, "pop end")
xs.reverse()
T.check_eq(xs[0], 5, "reverse")
xs.sort()
T.check_eq(xs, [0, 1, 2, 3, 4, 5], "sort")
T.check_eq(sorted([3, 1, 4, 1, 5, 9, 2, 6], reverse=True),
          [9, 6, 5, 4, 3, 2, 1, 1], "sorted reverse")
T.check_eq([x * 2 for x in [1, 2, 3]], [2, 4, 6], "list comp")
T.check_eq([x for x in range(10) if x % 2], [1, 3, 5, 7, 9], "filter comp")

T.section("tuple")
pt = (1, 2, 3)
T.check_eq(len(pt), 3, "len")
T.check_eq(pt[1], 2, "index")
a, b, c = pt
T.check_eq((a, b, c), (1, 2, 3), "unpack")
T.check_eq(pt + (4, 5), (1, 2, 3, 4, 5), "concat")

T.section("dict")
d = {"a": 1, "b": 2, "c": 3}
T.check_eq(len(d), 3, "len")
T.check_eq(d["a"], 1, "index")
T.check_eq(d.get("z", 99), 99, "get default")
d["d"] = 4
T.check_eq(d["d"], 4, "set new")
T.check(("a" in d) and ("z" not in d), "in / not in")
T.check_eq(sorted(d.keys()), ["a", "b", "c", "d"], "keys")
T.check_eq(sorted(d.values()), [1, 2, 3, 4], "values")
T.check_eq({k: v * 2 for k, v in d.items()},
          {"a": 2, "b": 4, "c": 6, "d": 8}, "dict comp")

T.section("dict update / merge")
d2 = d.copy()
d2.update({"e": 5, "a": 10})
T.check_eq(d2["a"], 10, "update overwrites")
T.check_eq(d2["e"], 5, "update adds")
T.check_eq({**d, "z": 26}["z"], 26, "spread merge")

T.section("set")
s = {1, 2, 3, 4}
T.check_eq(len(s), 4, "len")
T.check(3 in s, "in")
s.add(5); s.add(3)
T.check_eq(len(s), 5, "add dedup")
T.check_eq({1, 2, 3} | {3, 4, 5}, {1, 2, 3, 4, 5}, "union")
T.check_eq({1, 2, 3} & {2, 3, 4}, {2, 3}, "intersect")
T.check_eq({1, 2, 3} - {2}, {1, 3}, "diff")
T.check_eq({1, 2, 3} ^ {2, 3, 4}, {1, 4}, "symmetric diff")

T.section("frozenset")
fs = frozenset([1, 2, 3])
T.check_eq(len(fs), 3, "len")
T.check(1 in fs, "in")
T.check_raises(AttributeError, lambda: fs.add(4))

T.run()
