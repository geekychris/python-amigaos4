"""fireworks.py — particle-burst animation demo.

A rocket launches from the bottom, arcs up, then explodes into
coloured particles that fall with gravity + drag. New rocket every
few seconds. Pure fill_rect + dot — no bitmaps needed.

Controls:
    space  → launch a rocket now
    ESC / close → quit

Run:
    python3 python3:examples/fireworks.py
"""
import sys, os, time, random
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga

W, H = 480, 320
GRAV = 0.15
DRAG = 0.985
LIFE = 55           # frames a particle lives
BURST_N = 45        # particles per burst
COLOURS = (1, 2, 3)   # workbench palette; 0 is bg


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "pen")

    def __init__(self, x, y, vx, vy, pen):
        self.x, self.y = x, y
        self.vx, self.vy = vx, vy
        self.life = LIFE
        self.pen = pen

    def step(self):
        self.vy += GRAV
        self.vx *= DRAG
        self.vy *= DRAG
        self.x += self.vx
        self.y += self.vy
        self.life -= 1

    @property
    def alive(self):
        return self.life > 0 and 0 <= self.y < H


class Rocket:
    __slots__ = ("x", "y", "vy", "burst_at", "pen")

    def __init__(self):
        self.x = random.randint(80, W - 80)
        self.y = H - 4
        self.vy = -random.uniform(4.5, 6.5)
        self.burst_at = random.randint(60, 110)   # y-coordinate to explode
        self.pen = random.choice(COLOURS)

    def step(self):
        self.y += self.vy
        self.vy += GRAV * 0.4

    @property
    def exploded(self):
        return self.y <= self.burst_at or self.vy >= 0


def burst(x, y):
    """Return a list of Particle for one firework explosion."""
    particles = []
    for _ in range(BURST_N):
        # Isotropic-ish scatter, favoring outward directions.
        ang = random.uniform(0, 6.28318)
        spd = random.uniform(1.2, 3.8)
        vx = spd * (0.5 - random.random() + 0.5) * (1 if random.random() > 0.5 else -1)
        # Use ang for both to get a real ring — simpler:
        import math
        vx = math.cos(ang) * spd
        vy = math.sin(ang) * spd - 1.0     # small upward bias
        particles.append(Particle(x, y, vx, vy, random.choice(COLOURS)))
    return particles


def main():
    handle = _amiga.open_window(
        title="Python fireworks",
        left=60, top=40, width=W, height=H,
        idcmp=_amiga.IDCMP_CLOSEWINDOW | _amiga.IDCMP_VANILLAKEY,
    )
    print(f"fireworks: window @ {hex(handle)}", flush=True)
    rockets   = []
    particles = []
    last_spawn = 0.0

    try:
        _amiga.clear_window(handle, 0)
        _amiga.draw_text(handle, 8, H - 12,
                         "fireworks: SPACE launch, ESC quit", 1)
        running = True
        while running:
            now = time.monotonic()
            if now - last_spawn > 1.6 and len(rockets) < 3:
                rockets.append(Rocket())
                last_spawn = now

            # Repaint frame (full clear is fine — sparse scene).
            _amiga.clear_window(handle, 0)
            _amiga.draw_text(handle, 8, H - 12,
                             "fireworks: SPACE launch, ESC quit", 1)

            # Rockets: step + draw trail.
            still_flying = []
            for r in rockets:
                r.step()
                _amiga.dot(handle, int(r.x), int(r.y), 3, r.pen)
                if r.exploded:
                    particles.extend(burst(int(r.x), int(r.y)))
                else:
                    still_flying.append(r)
            rockets = still_flying

            # Particles: step + draw.
            alive_p = []
            for p in particles:
                p.step()
                if p.alive:
                    _amiga.dot(handle, int(p.x), int(p.y), 2, p.pen)
                    alive_p.append(p)
            particles = alive_p

            ev = _amiga.wait_message(handle, 0.035)
            if ev is None:
                continue
            cls = ev["class"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                running = False
            elif cls == _amiga.IDCMP_VANILLAKEY:
                if ev["code"] == 27:
                    running = False
                elif ev["code"] == 32:   # SPACE
                    rockets.append(Rocket())
    finally:
        _amiga.close_window(handle)
        print("fireworks: closed", flush=True)


if __name__ == "__main__":
    main()
