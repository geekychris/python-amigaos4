"""Functions: defaults, kwargs, *args, closures, decorators, lambdas."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("basic")
def add(a, b): return a + b
T.check_eq(add(2, 3), 5, "positional")
T.check_eq(add(a=2, b=3), 5, "kw")

def greet(name="world", greeting="hello"):
    return f"{greeting}, {name}"
T.check_eq(greet(), "hello, world", "defaults")
T.check_eq(greet("amiga"), "hello, amiga", "override 1st")
T.check_eq(greet(greeting="hi"), "hi, world", "override kw")

T.section("*args and **kwargs")
def collect(*a, **kw):
    return (a, sorted(kw.items()))
T.check_eq(collect(1, 2, 3),         ((1, 2, 3), []), "*args only")
T.check_eq(collect(x=1, y=2),         ((), [("x", 1), ("y", 2)]), "**kw only")
T.check_eq(collect(1, 2, k=3),        ((1, 2), [("k", 3)]), "mixed")

def sum_all(*nums, start=0):
    total = start
    for n in nums:
        total += n
    return total
T.check_eq(sum_all(1, 2, 3, 4), 10, "*nums")
T.check_eq(sum_all(1, 2, 3, start=100), 106, "start kw")

T.section("closures")
def make_counter():
    n = 0
    def bump():
        nonlocal n
        n += 1
        return n
    return bump
c = make_counter()
T.check_eq((c(), c(), c()), (1, 2, 3), "closure state")

def multiplier(k):
    return lambda x: x * k
double = multiplier(2)
triple = multiplier(3)
T.check_eq((double(5), triple(5)), (10, 15), "lambda closures independent")

T.section("decorators")
def bump(fn):
    def wrapped(*a, **kw):
        return fn(*a, **kw) + 1
    return wrapped

@bump
@bump
def zero():
    return 0
T.check_eq(zero(), 2, "stacked decorators")

def with_prefix(prefix):
    def deco(fn):
        def wrapped(*a, **kw):
            return prefix + fn(*a, **kw)
        return wrapped
    return deco

@with_prefix("[AMIGA] ")
def say(msg):
    return msg

T.check_eq(say("boot"), "[AMIGA] boot", "parametric decorator")

T.section("recursion")
def fact(n):
    return 1 if n <= 1 else n * fact(n - 1)
T.check_eq(fact(10), 3628800, "fact(10)")

def fib(n, memo={0: 0, 1: 1}):
    if n not in memo:
        memo[n] = fib(n - 1) + fib(n - 2)
    return memo[n]
T.check_eq(fib(30), 832040, "fib(30) memoised")

T.section("annotations")
def typed(name: str, count: int = 1) -> str:
    return f"{name} x{count}"
T.check_eq(typed("boing", 3), "boing x3", "annotated call")
T.check_eq(typed.__annotations__["count"], int, "annotation stored")

T.run()
