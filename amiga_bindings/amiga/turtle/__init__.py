"""
amiga.turtle — subset of Python's `turtle` module, backed by our
native `_amiga` window+drawing primitives.

The goal is running grantjenks/free-python-games games (snake, paint,
tron, pong, ...) on OS4 with real Intuition windows.  We implement
just the API surface those games use:

  setup(w, h, x=0, y=0)   title(str)   bgcolor(c)   done()   update()
  hideturtle()   tracer(n)
  penup()/up()   pendown()/down()
  goto(x, y)   pos()   xcor()   ycor()
  forward(n)/fd   back(n)/bk   left(deg)/lt   right(deg)/rt
  dot(size, color=None)   color(fg[, bg])
  begin_fill() / end_fill()   clear()   reset()
  listen()   onkey(fn, key)   onscreenclick(fn, btn=1)
  ontimer(fn, ms)
  exitonclick()

Coordinate system matches turtle: origin (0,0) at window center,
positive Y = up.  We flip Y and translate for Intuition's top-left
coord system inside every draw call.

Not implemented: begin_fill/end_fill (draws outlines only for now),
turtle shapes, stamps, custom fonts, real Screen class.
"""
import math
import time
import threading

try:
    import _amiga as _n
except ImportError:
    raise ImportError("amiga.turtle needs the _amiga native module (Phase 6.5+)")


# --- module-level state ------------------------------------------------

_state = {
    "handle": None,
    "width": 400,
    "height": 300,
    "left": 100,
    "top": 100,
    "title": "Python Turtle",
    "bg_pen": 0,          # background pen (obtained on demand)
    "fg_pen": 1,          # current foreground pen (default = black on WB)
    "pen_down": True,
    "x": 0.0,             # turtle position, turtle coords (origin=centre)
    "y": 0.0,
    "heading": 0.0,       # degrees; 0 = east, 90 = north
    "tracer_n": 1,        # 0 = manual update() only, >=1 = auto redraw
    "tracer_counter": 0,
    "onkey_map": {},      # key(str) -> callback
    "on_click": None,     # (fn, button)
    "timers": [],         # list of (fire_at, fn)
    "pen_cache": {},      # (r,g,b) -> allocated pen
    "next_pen_cache_slot": 0,
    "closed": False,
    "running": False,
}


# --- colour handling ---------------------------------------------------

# Named colours mapped to 8-bit RGB.  Extend as needed.
_NAMED = {
    "black":   (  0,   0,   0),
    "white":   (255, 255, 255),
    "red":     (255,   0,   0),
    "green":   (  0, 200,   0),
    "blue":    (  0,   0, 255),
    "yellow":  (255, 255,   0),
    "cyan":    (  0, 255, 255),
    "magenta": (255,   0, 255),
    "orange":  (255, 165,   0),
    "purple":  (128,   0, 128),
    "pink":    (255, 192, 203),
    "brown":   (139,  69,  19),
    "grey":    (128, 128, 128),
    "gray":    (128, 128, 128),
    "lightgray": (200, 200, 200),
    "darkgray":  ( 64,  64,  64),
}


def _resolve_color(spec):
    """turtle accepts 'red', '#rrggbb', or (r,g,b) triples."""
    if isinstance(spec, tuple) and len(spec) == 3:
        r, g, b = spec
        if all(isinstance(v, float) for v in (r, g, b)) and max(r, g, b) <= 1.0:
            r, g, b = int(r * 255), int(g * 255), int(b * 255)
        return int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF
    if isinstance(spec, str):
        s = spec.strip().lower()
        if s.startswith("#") and len(s) == 7:
            return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)
        return _NAMED.get(s, (0, 0, 0))
    return (0, 0, 0)


def _pen_for(spec):
    """Get an Amiga pen index for a turtle colour spec, caching."""
    rgb = _resolve_color(spec)
    if rgb in _state["pen_cache"]:
        return _state["pen_cache"][rgb]
    if _state["handle"] is None:
        return 1
    pen = _n.obtain_pen(_state["handle"], *rgb)
    if pen is None:
        pen = 1
    _state["pen_cache"][rgb] = pen
    return pen


# --- coordinate transform ----------------------------------------------

def _to_screen(tx, ty):
    """Turtle coords (origin=centre, y-up) → Intuition inner coords
    (origin=top-left, y-down)."""
    sx = int(tx + _state["width"] / 2)
    sy = int(_state["height"] / 2 - ty)
    return sx, sy


# --- window lifecycle --------------------------------------------------

def setup(width=400, height=300, startx=None, starty=None):
    """Turtle setup(): open the window."""
    _state["width"] = int(width)
    _state["height"] = int(height)
    if startx is not None:
        _state["left"] = int(startx)
    if starty is not None:
        _state["top"] = int(starty)
    if _state["handle"] is None:
        _state["handle"] = _n.open_window(
            title=_state["title"],
            left=_state["left"], top=_state["top"],
            width=_state["width"], height=_state["height"],
            idcmp=(_n.IDCMP_CLOSEWINDOW | _n.IDCMP_VANILLAKEY
                   | _n.IDCMP_MOUSEBUTTONS | _n.IDCMP_RAWKEY),
        )


def title(txt):
    _state["title"] = str(txt)
    # We can't change the title of an open window without SetWindowTitles;
    # add that entry later.  For now, just note it.


def bgcolor(color):
    _state["bg_pen"] = _pen_for(color)
    _redraw_bg()


def _redraw_bg():
    if _state["handle"] is not None:
        _n.clear_window(_state["handle"], _state["bg_pen"])


def color(fg, bg=None):
    _state["fg_pen"] = _pen_for(fg)
    if bg is not None:
        _state["bg_pen"] = _pen_for(bg)


# --- pen state ---------------------------------------------------------

def penup():  _state["pen_down"] = False
def pendown(): _state["pen_down"] = True
up = penup
down = pendown


def hideturtle(): pass   # we don't draw a cursor sprite anyway
def showturtle(): pass


def tracer(n=1, delay=None):
    _state["tracer_n"] = max(0, int(n))
    _state["tracer_counter"] = 0


def update():
    """Force a refresh (no-op — Intuition draws immediately)."""
    pass


# --- movement + drawing ------------------------------------------------

def goto(x, y=None):
    if y is None:
        # goto((x,y))
        x, y = x
    x, y = float(x), float(y)
    if _state["pen_down"] and _state["handle"] is not None:
        x0, y0 = _to_screen(_state["x"], _state["y"])
        x1, y1 = _to_screen(x, y)
        _n.draw_line(_state["handle"], x0, y0, x1, y1, _state["fg_pen"])
    _state["x"] = x
    _state["y"] = y


setpos = goto
setposition = goto


def pos():          return (_state["x"], _state["y"])
def xcor():         return _state["x"]
def ycor():         return _state["y"]
def heading():      return _state["heading"]


def forward(n):
    rad = math.radians(_state["heading"])
    nx = _state["x"] + n * math.cos(rad)
    ny = _state["y"] + n * math.sin(rad)
    goto(nx, ny)
fd = forward


def back(n):
    forward(-n)
bk = back


def left(deg):
    _state["heading"] = (_state["heading"] + deg) % 360.0
lt = left


def right(deg):
    _state["heading"] = (_state["heading"] - deg) % 360.0
rt = right


def setheading(deg):
    _state["heading"] = float(deg) % 360.0
seth = setheading


def home():
    _state["x"] = _state["y"] = 0.0
    _state["heading"] = 0.0


def dot(size, col=None):
    if col is not None:
        pen = _pen_for(col)
    else:
        pen = _state["fg_pen"]
    if _state["handle"] is not None:
        sx, sy = _to_screen(_state["x"], _state["y"])
        _n.dot(_state["handle"], sx, sy, max(1, int(size)), pen)


def clear():
    _redraw_bg()


def reset():
    home()
    clear()


# --- event bindings ----------------------------------------------------

def listen():
    pass   # we're always listening once the window is open


def onkey(fn, key):
    if fn is None:
        _state["onkey_map"].pop(key, None)
    else:
        _state["onkey_map"][key] = fn


onkeypress = onkey


def onscreenclick(fn, btn=1):
    _state["on_click"] = (fn, btn)


def ontimer(fn, ms):
    _state["timers"].append((time.monotonic() + ms / 1000.0, fn))


# --- event loop --------------------------------------------------------

# Raw-key to VanillaKey mapping isn't exact for arrow keys; we translate
# the common ones so freegames' ('Up','Down','Left','Right','w','a','s','d')
# bindings work.
_RAWKEY_MAP = {
    0x4C: "Up",
    0x4D: "Down",
    0x4F: "Left",
    0x4E: "Right",
    0x40: "space",
    0x45: "Escape",
    0x44: "Return",
}


def _dispatch_key(name):
    fn = _state["onkey_map"].get(name)
    if fn is None:
        return False
    try:
        fn()
    except Exception as e:
        print(f"[turtle] onkey({name}) raised: {e}")
    return True


def _tick_timers():
    now = time.monotonic()
    due, keep = [], []
    for at, fn in _state["timers"]:
        (due if now >= at else keep).append((at, fn))
    _state["timers"] = keep
    for _, fn in due:
        try:
            fn()
        except Exception as e:
            print(f"[turtle] ontimer raised: {e}")


def done():
    """Enter the main event loop until the window is closed."""
    if _state["handle"] is None:
        setup()
    _state["running"] = True
    while _state["running"]:
        # 20ms tick — timer resolution + IDCMP polling interval.
        ev = _n.wait_message(_state["handle"], 0.02)
        _tick_timers()
        if ev is None:
            continue
        cls = ev["class"]
        if cls == _n.IDCMP_CLOSEWINDOW:
            _state["running"] = False
            break
        if cls == _n.IDCMP_VANILLAKEY:
            code = ev["code"]
            if code == 27:
                _state["running"] = False
                break
            ch = chr(code) if 32 <= code < 127 else None
            if ch is not None:
                _dispatch_key(ch)
        elif cls == _n.IDCMP_RAWKEY:
            name = _RAWKEY_MAP.get(ev["code"])
            if name:
                _dispatch_key(name)
        elif cls == _n.IDCMP_MOUSEBUTTONS:
            oc = _state["on_click"]
            if oc:
                fn, _btn = oc
                # Convert Intuition mouse coords → turtle coords.
                mx = ev["mouse_x"] - _state["width"] / 2
                my = _state["height"] / 2 - ev["mouse_y"]
                try:
                    fn(mx, my)
                except Exception as e:
                    print(f"[turtle] onscreenclick raised: {e}")
    _cleanup()


exitonclick = done   # freegames often uses this synonym


def _cleanup():
    if _state["handle"] is not None:
        # Release any pens we allocated.
        for pen in _state["pen_cache"].values():
            try:
                _n.release_pen(_state["handle"], pen)
            except Exception:
                pass
        _state["pen_cache"] = {}
        _n.close_window(_state["handle"])
        _state["handle"] = None
    _state["closed"] = True


# --- extras for freegames — filled shapes ------------------------------

def filled_square(x, y, size, col=None):
    """Draw a filled square with its bottom-left corner at turtle (x, y).
    Handy for freegames' `square(x, y, size, name)` helper — the outline-
    only version you get from forward+left doesn't actually fill.
    """
    if col is not None:
        pen = _pen_for(col)
    else:
        pen = _state["fg_pen"]
    if _state["handle"] is None:
        return
    x1, y1 = _to_screen(x, y + size)   # top-left in screen coords
    x2, y2 = _to_screen(x + size, y)   # bottom-right
    _n.fill_rect(_state["handle"], x1, y1, x2, y2, pen)


# --- no-ops so freegames' setups don't crash --------------------------

# begin_fill / end_fill are stubs — use filled_square directly for real
# fills in the meantime.
def begin_fill(): pass
def end_fill():   pass
def screensize(*a, **kw): return _state["width"], _state["height"]
def register_shape(*a, **kw): pass
def shape(*a, **kw): pass
def speed(*a, **kw): pass
def pensize(*a, **kw): pass
def width(*a, **kw): pass
def bye(): _state["running"] = False
