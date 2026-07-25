"""If / for / while / match / break / continue / else clauses."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("if/elif/else")
def classify(n):
    if n < 0:      return "negative"
    elif n == 0:   return "zero"
    elif n < 100:  return "small"
    else:          return "large"
T.check_eq(classify(-5), "negative", "neg")
T.check_eq(classify(0), "zero", "zero")
T.check_eq(classify(42), "small", "small")
T.check_eq(classify(1000), "large", "large")

T.section("for")
total = 0
for i in range(1, 11):
    total += i
T.check_eq(total, 55, "sum 1..10")

for i, v in enumerate(["a", "b", "c"]):
    if i == 1 and v != "b":
        T.check(False, "enumerate misaligned")
        break
else:
    T.check(True, "enumerate walked all")

pairs = list(zip("abc", [1, 2, 3]))
T.check_eq(pairs, [("a", 1), ("b", 2), ("c", 3)], "zip")

T.section("while")
n, count = 100, 0
while n > 1:
    n = n // 2 if n % 2 == 0 else 3 * n + 1
    count += 1
T.check_eq(count, 25, "collatz(100) steps")

T.section("break / continue")
found = None
for x in [1, 3, 5, 7, 9]:
    if x > 4:
        found = x
        break
T.check_eq(found, 5, "break exits early")

evens = []
for x in range(10):
    if x % 2:
        continue
    evens.append(x)
T.check_eq(evens, [0, 2, 4, 6, 8], "continue skips odds")

T.section("for/else")
def has_negative(xs):
    for x in xs:
        if x < 0:
            return True
    else:
        return False
T.check(not has_negative([1, 2, 3]), "for/else negatives absent")
T.check(has_negative([1, -2, 3]), "for/else negatives present")

T.section("match")  # PEP 634 pattern matching (3.10+)
def describe(value):
    match value:
        case 0:                        return "zero"
        case int() if value < 0:       return "negative int"
        case int():                    return "positive int"
        case [x]:                      return f"1-list of {x!r}"
        case [x, y]:                   return f"2-list of {x!r},{y!r}"
        case {"type": t}:              return f"dict with type={t!r}"
        case str() as s if len(s) > 5: return "long string"
        case _:                        return "other"

T.check_eq(describe(0), "zero", "match int 0")
T.check_eq(describe(-3), "negative int", "match int guard")
T.check_eq(describe(42), "positive int", "match int")
T.check_eq(describe([9]), "1-list of 9", "match list 1")
T.check_eq(describe([1, 2]), "2-list of 1,2", "match list 2")
T.check_eq(describe({"type": "amiga"}), "dict with type='amiga'", "match dict")
T.check_eq(describe("floppy"), "long string", "match guard")
T.check_eq(describe(3.14), "other", "match wildcard")

T.run()
