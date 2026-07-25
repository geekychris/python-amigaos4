"""Exception handling: raise, try/except/finally/else, custom, chaining."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("basic try/except")
def divide(a, b):
    try:
        return a / b
    except ZeroDivisionError:
        return None
T.check_eq(divide(10, 2), 5, "no error")
T.check(divide(10, 0) is None, "caught")

T.section("multiple except")
def classify(x):
    try:
        return int(x)
    except ValueError:
        return "not-a-number"
    except TypeError:
        return "wrong-type"

T.check_eq(classify("42"), 42, "int ok")
T.check_eq(classify("abc"), "not-a-number", "ValueError")
T.check_eq(classify(None), "wrong-type", "TypeError")

T.section("try / except / else / finally")
log = []
def whole_dance(bad):
    result = None
    try:
        log.append("try")
        if bad:
            raise RuntimeError("x")
    except RuntimeError:
        log.append("except")
        result = "failed"
    else:
        log.append("else")
        result = "great"
    finally:
        log.append("finally")
    return result

log.clear(); r = whole_dance(False)
T.check_eq(r, "great", "else return")
T.check_eq(log, ["try", "else", "finally"], "else path")

log.clear(); r = whole_dance(True)
T.check_eq(r, "failed", "except return")
T.check_eq(log, ["try", "except", "finally"], "except path")

T.section("custom exceptions")
class BridgeError(Exception):
    def __init__(self, msg, errno=None):
        super().__init__(msg)
        self.errno = errno

try:
    raise BridgeError("timeout", errno=110)
except BridgeError as e:
    T.check_eq(str(e), "timeout", "custom __str__")
    T.check_eq(e.errno, 110, "custom attr")

T.section("chaining")
def unwrap():
    try:
        int("boom")
    except ValueError as v:
        raise RuntimeError("outer") from v

try:
    unwrap()
except RuntimeError as r:
    T.check(r.__cause__ is not None, "cause set")
    T.check(isinstance(r.__cause__, ValueError), "cause type")

T.section("exception groups (3.11+)")
try:
    raise ExceptionGroup("mixed", [ValueError("a"), TypeError("b")])
except* ValueError as vg:
    T.check_eq(len(vg.exceptions), 1, "except* ValueError caught 1")
except* TypeError as tg:
    T.check_eq(len(tg.exceptions), 1, "except* TypeError caught 1")

T.section("finally on generator")
def cleaning():
    try:
        yield 1
        yield 2
    finally:
        log.append("gen-cleanup")

log.clear()
g = cleaning()
next(g)
g.close()
T.check_eq(log, ["gen-cleanup"], "close triggers finally")

T.run()
