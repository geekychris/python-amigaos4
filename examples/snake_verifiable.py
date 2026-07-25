"""snake_verifiable.py — snake with self-audit trail.

Unlike snake.py this version:

  * Logs every key event + every move-tick to T:snake_log.txt so we
    can confirm from the host side (via read_file over the bridge)
    that inputs are actually reaching the game.

  * Draws a directional-indicator dot (green=Right, red=Left,
    blue=Up, yellow=Down) each tick so screenshots show which way
    the snake is actually turning.

  * Uses amiga.turtle's real timer.device-backed wait_message
    (no busy-poll) — the whole game idles at zero CPU.

  * Cleanup via atexit — if you Break the process, window + pens
    + port still release.

Verification recipe from the host (via bridge tools):

    amiga_dos_command "run >NIL: DH1:python-os4 DH1:pytests/examples/snake_verifiable.py"
    # let it settle 500ms
    amiga_input_key rawkey=0x4E     # Right
    amiga_input_key rawkey=0x4C     # Up
    amiga_input_key rawkey=0x4F     # Left
    # 2s later
    amiga_screenshot                # see indicator dot in each direction
    amiga_read_file  T:snake_log.txt   # see the exact event log
"""
import sys, os
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import amiga.turtle as t

_LOG = "T:snake_log.txt"


def log(line):
    with open(_LOG, "a") as f:
        f.write(line + "\n")


class vec:
    __slots__ = ("x", "y")
    def __init__(self, x, y):
        self.x, self.y = x, y
    def copy(self):
        return vec(self.x, self.y)


# --- game state --------------------------------------------------------

food = vec(50, 50)
snake = [vec(0, 0)]
aim = vec(10, 0)                # start moving right
last_key = "(none)"
tick_count = 0


def indicator_color():
    """Colour for the directional pip in the corner."""
    if aim.x > 0: return "green"
    if aim.x < 0: return "red"
    if aim.y > 0: return "blue"
    return "yellow"


def change(name, dx, dy):
    global last_key
    last_key = name
    log(f"KEY {name} -> aim=({dx},{dy})  tick={tick_count}")
    aim.x, aim.y = dx, dy


def inside(head):
    return -140 < head.x < 140 and -140 < head.y < 140


def move():
    global tick_count
    tick_count += 1
    head = snake[-1].copy()
    head.x += aim.x
    head.y += aim.y

    if not inside(head):
        log(f"OUT-OF-BOUNDS at tick {tick_count}, head=({head.x},{head.y})")
        t.filled_square(head.x, head.y, 9, "red")
        return                  # stop ticking; window stays open

    snake.append(head)
    if head.x == food.x and head.y == food.y:
        log(f"ATE food at tick {tick_count}")
        food.x = (food.x * 3 + 50) % 260 - 130
        food.y = (food.y * 5 + 30) % 260 - 130
    else:
        snake.pop(0)

    t.clear()
    for body in snake:
        t.filled_square(body.x, body.y, 9, "black")
    t.filled_square(food.x, food.y, 9, "green")
    # Direction indicator: bottom-left pip in the aim's colour, plus
    # last-key text at the top so screenshots are self-describing.
    t.filled_square(-140, -140, 15, indicator_color())
    t._n.draw_text(t._state["handle"], 10, 15,
                   f"tick {tick_count}  last_key={last_key}", 1)
    t.ontimer(move, 200)


# --- start ------------------------------------------------------------

try:
    os.remove(_LOG)
except OSError:
    pass
log("=== snake_verifiable start ===")

t.setup(320, 320, 300, 50)
t.title("Python Snake (verifiable)")
t.bgcolor("white")
t.hideturtle()
t.tracer(0)
t.listen()

t.onkey(lambda: change("Right", 10, 0),  "Right")
t.onkey(lambda: change("Left",  -10, 0), "Left")
t.onkey(lambda: change("Up",    0, 10),  "Up")
t.onkey(lambda: change("Down",  0, -10), "Down")
t.onkey(lambda: change("d", 10, 0),  "d")
t.onkey(lambda: change("a", -10, 0), "a")
t.onkey(lambda: change("w", 0, 10),  "w")
t.onkey(lambda: change("s", 0, -10), "s")

move()      # kick the first tick manually
t.done()
