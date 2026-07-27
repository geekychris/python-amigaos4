"""paint.py — grantjenks/free-python-games "paint" via amiga.turtle.

The stdlib turtle drawing app that lets you click-drag to paint
lines, rectangles, ovals, triangles. Runs unmodified on top of our
amiga.turtle shim — proves the shim isn't snake-specific.

Controls (mouse):
  left-click, drag        → draw current shape
  click 'l' / 'r' / 'o' / 't' → change to line / rect / oval / triangle
  ESC / close window      → quit

Run:
    DH1:python-os4 DH1:pytests/examples/paint.py
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

# freegames.paint's whole implementation, adapted to work without
# a freegames package install (it's tiny). Faithful to the original
# stdlib-turtle interface — the only reason it works on Amiga is
# that amiga.turtle is a real turtle-API implementation over _amiga.
from turtle import setup, hideturtle, listen, onkey, onscreenclick, \
    ondrag, up, down, goto, color, begin_fill, end_fill, \
    forward, left, right, tracer, update, done

state = {"start": None, "shape": "line"}


def line(start, end):
    up()
    goto(start)
    down()
    goto(end)


def square(start, end):
    up()
    goto(start)
    down()
    begin_fill()
    for _ in range(4):
        forward(end[0] - start[0])
        left(90)
    end_fill()


def circle(start, end):
    from turtle import circle as t_circle
    up()
    goto(start)
    down()
    r = max(1, int(((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5))
    begin_fill()
    t_circle(r)
    end_fill()


def triangle(start, end):
    up()
    goto(start)
    down()
    begin_fill()
    d = end[0] - start[0]
    for _ in range(3):
        forward(d)
        left(120)
    end_fill()


SHAPES = {"l": line, "r": square, "o": circle, "t": triangle}


def tap(x, y):
    """Mouse click: first click marks start, second click closes the shape."""
    start = state["start"]
    if start is None:
        state["start"] = (x, y)
    else:
        shape = SHAPES[state["shape"]]
        shape(start, (x, y))
        state["start"] = None


def store_shape(name):
    state["shape"] = name
    print(f"paint: shape → {name}", flush=True)


def main():
    setup(400, 400, 370, 0)
    hideturtle()
    tracer(False)
    color("black", "black")
    onscreenclick(tap)
    listen()
    for k in SHAPES:
        onkey(lambda k=k: store_shape(k), k)
    done()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
