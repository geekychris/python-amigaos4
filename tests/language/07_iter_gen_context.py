"""Iterators, generators, comprehensions, context managers."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("iterators")
class Fib:
    def __init__(self, n):
        self.n = n
    def __iter__(self):
        a, b = 0, 1
        for _ in range(self.n):
            yield a
            a, b = b, a + b

T.check_eq(list(Fib(8)), [0, 1, 1, 2, 3, 5, 8, 13], "custom iterator")

it = iter([10, 20, 30])
T.check_eq(next(it), 10, "next 1")
T.check_eq(next(it), 20, "next 2")
T.check_eq(next(it), 30, "next 3")
T.check_raises(StopIteration, next, it)

T.section("generator functions")
def counter(start=0):
    while True:
        yield start
        start += 1

c = counter(100)
T.check_eq([next(c) for _ in range(3)], [100, 101, 102], "infinite gen")

def squares_until(limit):
    n = 1
    while n * n < limit:
        yield n * n
        n += 1
T.check_eq(list(squares_until(50)), [1, 4, 9, 16, 25, 36, 49], "gen stop")

T.section("generator send / throw")
def echo():
    v = None
    while True:
        v = yield v
gen = echo()
next(gen)               # prime
T.check_eq(gen.send("hi"), "hi", "send")
T.check_eq(gen.send(42), 42, "send int")

T.section("yield from")
def one_two(): yield 1; yield 2
def three_four(): yield 3; yield 4
def all_four():
    yield from one_two()
    yield from three_four()
T.check_eq(list(all_four()), [1, 2, 3, 4], "yield from")

T.section("comprehensions")
T.check_eq([x**2 for x in range(5)], [0, 1, 4, 9, 16], "list comp")
T.check_eq({x**2 for x in [1, 2, 2, 3]}, {1, 4, 9}, "set comp")
T.check_eq({x: x**2 for x in range(4)}, {0: 0, 1: 1, 2: 4, 3: 9}, "dict comp")
T.check_eq(sum(x*x for x in range(10)), 285, "gen expr in sum")
T.check_eq([(x, y) for x in range(3) for y in range(3) if x != y and x+y == 3],
          [(1, 2), (2, 1)], "nested + filter")

T.section("context managers - class-based")
class Trace:
    def __init__(self): self.log = []
    def __enter__(self):
        self.log.append("enter")
        return self
    def __exit__(self, exc_type, exc, tb):
        self.log.append(f"exit exc={exc_type.__name__ if exc_type else None}")
        return False   # don't suppress

tr = Trace()
with tr:
    tr.log.append("body")
T.check_eq(tr.log, ["enter", "body", "exit exc=None"], "normal exit")

tr = Trace()
try:
    with tr:
        raise ValueError("boom")
except ValueError:
    pass
T.check_eq(tr.log, ["enter", "exit exc=ValueError"], "exception exit")

T.section("context manager - contextmanager decorator")
from contextlib import contextmanager
@contextmanager
def timer(log):
    log.append("start")
    try:
        yield log
    finally:
        log.append("stop")

log = []
with timer(log) as l:
    l.append("work")
T.check_eq(log, ["start", "work", "stop"], "contextmanager")

T.run()
