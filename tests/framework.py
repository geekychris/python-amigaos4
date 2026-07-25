"""
Tiny test framework for python-amigaos4.

Every test script imports this and uses `t.check(cond, name)` /
`t.section("...")` / `t.run()`. On completion, prints a single
final line of `PASS: <script>` or `FAIL: <script>: N/M passed`
that `tests/run-tests.sh` can grep for from the host.

Kept intentionally trivial — no unittest, no pytest, no
argparse. Just enough to be self-contained on the Amiga side
with only the built-in Python 3.12 stdlib.
"""
import sys


class TestRunner:
    def __init__(self, name):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.failures = []
        self._current_section = None

    def section(self, title):
        """Start a new logical group of checks."""
        self._current_section = title

    def check(self, cond, label):
        """Record a pass/fail. `label` should be a short descriptor."""
        full = f"[{self._current_section}] {label}" if self._current_section else label
        if cond:
            self.passed += 1
        else:
            self.failed += 1
            self.failures.append(full)

    def check_eq(self, actual, expected, label):
        """Convenience: assert equal with helpful diff on fail."""
        ok = actual == expected
        if not ok:
            label = f"{label}  (got {actual!r}, want {expected!r})"
        self.check(ok, label)

    def skip(self, why):
        """Print a SKIP line and exit 0 — used when a required stdlib
        module is missing on this Python port."""
        print(f"SKIP: {self.name}  ({why})")
        sys.exit(0)

    def try_import(self, module_name):
        """Return the imported module or call self.skip() if unavailable."""
        try:
            return __import__(module_name)
        except ImportError as e:
            self.skip(f"{module_name} not available: {e}")

    def check_raises(self, exc_type, callable_, *args, **kwargs):
        """Record pass if calling `callable_(*args, **kwargs)` raises exc_type."""
        label = f"raises {exc_type.__name__}: {callable_.__name__}"
        try:
            callable_(*args, **kwargs)
            self.check(False, label + " (no exception raised)")
        except exc_type:
            self.check(True, label)
        except BaseException as e:
            self.check(False, f"{label} (got {type(e).__name__}: {e})")

    def run(self):
        """Print the final summary line and exit with status 0 or 1."""
        total = self.passed + self.failed
        if self.failed == 0:
            print(f"PASS: {self.name}  ({self.passed}/{total})")
            sys.exit(0)
        else:
            print(f"FAIL: {self.name}  ({self.passed}/{total} passed)")
            for f in self.failures[:10]:
                print(f"  - {f}")
            if len(self.failures) > 10:
                print(f"  ... and {len(self.failures) - 10} more")
            sys.exit(1)


def new(name):
    """Convenience factory so tests can `t = framework.new(__file__)`.

    Installs a sys.excepthook that prints a FAIL line for any uncaught
    exception — otherwise, the Amiga port sometimes silent-exits on
    exceptions without ever writing to stderr.
    """
    import os
    basename = os.path.basename(name).rsplit(".", 1)[0]

    def _hook(exc_type, exc, tb):
        if exc_type is SystemExit:
            return  # normal exit path
        print(f"FAIL: {basename}  (uncaught {exc_type.__name__}: {exc})")
    sys.excepthook = _hook
    return TestRunner(basename)


def guard(fn):
    """Wrap a test main so any escaping exception prints a FAIL line
    instead of a silent exit (Python's default sys.excepthook may not
    reach the console reliably on the Amiga port).

    Usage:
        def main():
            t = framework.new(__file__)
            ...
            t.run()
        framework.guard(main)
    """
    import os
    try:
        fn()
    except SystemExit:
        raise
    except BaseException as e:
        name = os.path.basename(sys.argv[0]).rsplit(".", 1)[0] if sys.argv else "?"
        print(f"FAIL: {name}  (uncaught {type(e).__name__}: {e})")
        sys.exit(1)
