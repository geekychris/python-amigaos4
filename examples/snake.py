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
import sys, os
sys.path.insert(0, "DH1:pytests/amiga_bindings")

from random import randrange
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
    """Draw filled square at (x,y) with given size and colour name."""
    t.up()
    t.goto(x, y)
    t.down()
    t.begin_fill()
    t.color(name)
    # Use the underlying fill primitive: shim's dot() with size gives
    # a centred square; freegames.square wants a bottom-left origin one.
    # Approximate by drawing a filled rect via 4 forward+left calls.
    for _ in range(4):
        t.forward(size)
        t.left(90)
    t.end_fill()


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
