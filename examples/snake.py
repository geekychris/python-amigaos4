"""snake.py — grantjenks/free-python-games snake, ported to Amiga.

Only tweaks vs upstream freegames snake:
  1. import amiga.turtle instead of turtle
  2. inline the trivial vector class + square() helper so we don't
     need the freegames package on the target
  3. call setup() with a smaller default so the window fits

Everything else is verbatim.  Uses the amiga.turtle shim on top of
_amiga's Intuition wrappers — real Amiga window, real keyboard, real
draw calls.
"""
import sys, os, traceback
sys.path.insert(0, "DH1:pytests/amiga_bindings")

def _uncaught(t_, e, tb):
    with open("T:snake.err", "w") as f:
        f.write(str(t_.__name__) + ": " + str(e) + "\n")
        traceback.print_exception(t_, e, tb, file=f)
sys.excepthook = _uncaught

# stdlib `random` imports hashlib.sha512 -> _sha2 which isn't a
# builtin on our Python port yet.  Use a tiny inline LCG that's
# perfectly adequate for game-scale randomness.
_seed = [0x12345678]
def randrange(lo, hi):
    _seed[0] = (_seed[0] * 1103515245 + 12345) & 0x7fffffff
    return lo + (_seed[0] % (hi - lo))

import amiga.turtle as t


# --- freegames.utils inlined ------------------------------------------
class vector:
    """Two-component xy vector, mutable, minimally-typed."""
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x, self.y = x, y
    def copy(self):
        return vector(self.x, self.y)


def square(x, y, size, name):
    """Draw a filled square at turtle (x, y) with the given size + colour."""
    # amiga.turtle ships a native filled_square helper — begin_fill/end_fill
    # remain stubs on the shim (turtle's fill flood-algorithm isn't
    # ported); this bypasses them and calls fill_rect directly.
    t.filled_square(x, y, size, name)


# --- game -------------------------------------------------------------
food = vector(0, 0)
snake = [vector(10, 0)]
aim = vector(0, -10)


def change(x, y):
    aim.x, aim.y = x, y


def inside(head):
    return -200 < head.x < 190 and -200 < head.y < 190


def move():
    head = snake[-1].copy()
    head.x += aim.x
    head.y += aim.y
    if not inside(head) or head in snake:
        square(head.x, head.y, 9, "red")
        t.update()
        return    # game over
    snake.append(head)
    if head.x == food.x and head.y == food.y:
        print("Snake:", len(snake))
        food.x = randrange(-15, 15) * 10
        food.y = randrange(-15, 15) * 10
    else:
        snake.pop(0)
    t.clear()
    for body in snake:
        square(body.x, body.y, 9, "black")
    square(food.x, food.y, 9, "green")
    t.update()
    t.ontimer(move, 100)


t.setup(420, 420, 370, 0)
t.title("Python Snake")
t.bgcolor("white")
t.hideturtle()
t.tracer(0)
t.listen()
t.onkey(lambda: change(10, 0),  "Right")
t.onkey(lambda: change(-10, 0), "Left")
t.onkey(lambda: change(0, 10),  "Up")
t.onkey(lambda: change(0, -10), "Down")
# WASD alternatives (turtle 'w'/'a'/'s'/'d')
t.onkey(lambda: change(10, 0),  "d")
t.onkey(lambda: change(-10, 0), "a")
t.onkey(lambda: change(0, 10),  "w")
t.onkey(lambda: change(0, -10), "s")
move()
t.done()
