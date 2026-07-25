"""Classes: methods, inheritance, dunders, properties, dataclasses."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import framework
T = framework.new(__file__)

T.section("basic class")
class Volume:
    """Represents an Amiga volume like DH0: or RAM:."""
    def __init__(self, name, mb):
        self.name = name
        self.mb = mb
    def path(self, sub):
        return f"{self.name}{sub}"
    def __repr__(self):
        return f"Volume({self.name!r}, {self.mb})"
    def __eq__(self, other):
        return isinstance(other, Volume) and self.name == other.name

v = Volume("DH1:", 512)
T.check_eq(v.name, "DH1:", "attr")
T.check_eq(v.mb, 512, "attr int")
T.check_eq(v.path("lib/foo.py"), "DH1:lib/foo.py", "method")
T.check_eq(repr(v), "Volume('DH1:', 512)", "__repr__")
T.check_eq(v, Volume("DH1:", 0), "custom __eq__ (name only)")

T.section("inheritance")
class Assign(Volume):
    """A named ASSIGN — same API, different flavour."""
    def path(self, sub):
        return f"[ASSIGN {self.name}]{sub}"

a = Assign("PYTHONHOME:", 0)
T.check_eq(a.path("bin"), "[ASSIGN PYTHONHOME:]bin", "override")
T.check(isinstance(a, Volume), "isinstance parent")
T.check_eq(a.name, "PYTHONHOME:", "inherited __init__")

T.section("super() + mro")
class A:
    def tag(self): return "A"
class B(A):
    def tag(self): return "B->" + super().tag()
class C(B):
    def tag(self): return "C->" + super().tag()
T.check_eq(C().tag(), "C->B->A", "super chain")
T.check_eq([c.__name__ for c in C.__mro__], ["C", "B", "A", "object"], "mro")

T.section("dunder methods")
class Path:
    def __init__(self, s): self.s = s
    def __add__(self, other):
        if self.s.endswith(":") or self.s.endswith("/"):
            return Path(self.s + other)
        return Path(self.s + "/" + other)
    def __str__(self):  return self.s
    def __repr__(self): return f"Path({self.s!r})"
    def __len__(self):  return len(self.s)
    def __bool__(self): return bool(self.s)
    def __eq__(self, o): return isinstance(o, Path) and self.s == o.s
    def __hash__(self):  return hash(self.s)

p = Path("DH1:") + "lib" + "python3.12"
T.check_eq(str(p), "DH1:lib/python3.12", "custom __add__")
T.check_eq(len(p), 18, "__len__")
T.check(bool(Path("x")), "__bool__ truthy")
T.check(not bool(Path("")), "__bool__ falsy")
T.check_eq({Path("a"), Path("a"), Path("b")}, {Path("a"), Path("b")}, "hashable")

T.section("properties")
class Rectangle:
    def __init__(self, w, h):
        self._w = w; self._h = h
    @property
    def area(self):
        return self._w * self._h
    @property
    def w(self): return self._w
    @w.setter
    def w(self, value):
        if value < 0: raise ValueError("negative width")
        self._w = value

r = Rectangle(3, 4)
T.check_eq(r.area, 12, "computed property")
r.w = 10
T.check_eq(r.area, 40, "setter updates dep")
T.check_raises(ValueError, lambda: setattr(r, "w", -1))

T.section("classmethod / staticmethod")
class Counter:
    total = 0
    def __init__(self):
        Counter.total += 1
    @classmethod
    def created(cls):
        return cls.total
    @staticmethod
    def is_even(n):
        return n % 2 == 0

_ = [Counter() for _ in range(5)]
T.check_eq(Counter.created(), 5, "classmethod")
T.check(Counter.is_even(4), "staticmethod on class")
T.check(Counter().is_even(4), "staticmethod on instance")

T.section("dataclass")
from dataclasses import dataclass, field

@dataclass
class Event:
    name: str
    priority: int = 1
    tags: list = field(default_factory=list)

e = Event("boot")
T.check_eq(e.name, "boot", "positional")
T.check_eq(e.priority, 1, "default")
T.check_eq(e.tags, [], "factory default")
e2 = Event("boot")
T.check_eq(e, e2, "dataclass __eq__ generated")
e.tags.append("critical")
T.check_eq(len(e2.tags), 0, "factory yields independent instances")

T.run()
