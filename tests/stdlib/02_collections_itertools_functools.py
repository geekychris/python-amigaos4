"""Data-structure and functional-programming stdlib modules."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("collections.Counter")
from collections import Counter
c = Counter("mississippi")
T.check_eq(c["s"], 4, "s count")
T.check_eq(c["z"], 0, "missing = 0")
T.check_eq(c.most_common(2), [("i", 4), ("s", 4)], "most_common 2")

T.section("collections.defaultdict")
from collections import defaultdict
d = defaultdict(list)
d["a"].append(1); d["a"].append(2); d["b"].append(3)
T.check_eq(dict(d), {"a": [1, 2], "b": [3]}, "list default")

d2 = defaultdict(int)
for w in "the quick the brown the fox".split():
    d2[w] += 1
T.check_eq(d2["the"], 3, "int default counter")

T.section("collections.deque")
from collections import deque
q = deque([1, 2, 3])
q.appendleft(0); q.append(4)
T.check_eq(list(q), [0, 1, 2, 3, 4], "both ends")
T.check_eq(q.popleft(), 0, "popleft")
T.check_eq(q.pop(), 4, "pop")

T.section("collections.namedtuple")
from collections import namedtuple
Point = namedtuple("Point", ["x", "y"])
p = Point(3, 4)
T.check_eq(p.x, 3, "attr access")
T.check_eq(p[1], 4, "index access")
T.check_eq(p._asdict(), {"x": 3, "y": 4}, "_asdict")

T.section("itertools")
import itertools as it
T.check_eq(list(it.chain([1, 2], [3, 4])), [1, 2, 3, 4], "chain")
T.check_eq(list(it.combinations([1, 2, 3, 4], 2)),
          [(1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4)], "combinations")
T.check_eq(list(it.permutations("ab")), [("a", "b"), ("b", "a")], "permutations")
T.check_eq(list(it.repeat("x", 3)), ["x", "x", "x"], "repeat")

# infinite iterators + islice
T.check_eq(list(it.islice(it.count(10), 5)), [10, 11, 12, 13, 14], "islice(count)")
T.check_eq(list(it.islice(it.cycle("ab"), 5)), ["a", "b", "a", "b", "a"], "cycle")

# groupby (requires sorted input)
words = ["apple", "ant", "banana", "berry", "cherry"]
groups = [(k, list(g)) for k, g in it.groupby(words, key=lambda w: w[0])]
T.check_eq(groups, [("a", ["apple", "ant"]), ("b", ["banana", "berry"]), ("c", ["cherry"])],
          "groupby")

T.section("functools")
from functools import reduce, partial, lru_cache, cache

T.check_eq(reduce(lambda a, b: a + b, [1, 2, 3, 4]), 10, "reduce")
T.check_eq(reduce(lambda a, b: a * b, [1, 2, 3, 4], 1), 24, "reduce with init")

add_ten = partial(lambda a, b: a + b, 10)
T.check_eq(add_ten(5), 15, "partial")

@lru_cache(maxsize=None)
def slow_fib(n):
    if n < 2: return n
    return slow_fib(n - 1) + slow_fib(n - 2)
T.check_eq(slow_fib(50), 12586269025, "lru_cache")

@cache
def factorial(n):
    return 1 if n <= 1 else n * factorial(n - 1)
T.check_eq(factorial(20), 2432902008176640000, "@cache")

T.run()
