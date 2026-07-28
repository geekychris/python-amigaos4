"""starfield.py — animated 3D-perspective starfield in an Intuition window.

Stars fly out from the vanishing point toward the camera. Direct
_amiga primitives (fill_rect for erase + colored dots for stars) —
proves the graphics pipeline handles per-frame animation without
tearing on the sam460ex QEMU target.

Controls:
    ESC / close gadget → quit

Run:
    python3 python3:examples/starfield.py
"""
import sys, os, time, random
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga

W, H     = 480, 320
CX, CY   = W // 2, H // 2
NSTARS   = 80
Z_START  = 500        # far
Z_END    = 8          # near
SPEED    = 12         # perspective units per frame


class Star:
    __slots__ = ("x", "y", "z", "pen")

    def __init__(self):
        self.pen = random.choice((1, 2, 3))
        self.reset()

    def reset(self):
        # Random point in 3D space far from the camera.
        self.x = random.randint(-CX, CX)
        self.y = random.randint(-CY, CY)
        self.z = random.randint(Z_END + 10, Z_START)

    def step(self):
        self.z -= SPEED
        if self.z <= Z_END:
            self.reset()

    def project(self):
        # Perspective divide — stars nearer the camera move faster.
        k = 256.0 / self.z
        sx = int(self.x * k) + CX
        sy = int(self.y * k) + CY
        # Star gets bigger as it approaches.
        size = 1 + int((Z_START - self.z) / 120)
        return sx, sy, size


def main():
    handle = _amiga.open_window(
        title="Python starfield",
        left=80, top=60, width=W, height=H,
        idcmp=_amiga.IDCMP_CLOSEWINDOW | _amiga.IDCMP_VANILLAKEY,
    )
    print(f"starfield: window @ {hex(handle)}", flush=True)
    try:
        _amiga.clear_window(handle, 0)
        stars = [Star() for _ in range(NSTARS)]
        # Draw a status line once — non-animated.
        _amiga.draw_text(handle, 8, H - 12,
                         "starfield: ESC or close to quit", 1)

        running = True
        frame_no = 0
        while running:
            # No full clear — draw stars each frame, plus a fade box.
            # Full clear every 30 frames anyway to prevent drift.
            if frame_no % 30 == 0:
                _amiga.clear_window(handle, 0)
                _amiga.draw_text(handle, 8, H - 12,
                                 "starfield: ESC or close to quit", 1)

            # Erase previous star positions with black dots + step.
            for s in stars:
                sx, sy, size = s.project()
                if 0 <= sx < W and 0 <= sy < H:
                    _amiga.dot(handle, sx, sy, size + 1, 0)
                s.step()

            # Draw new positions.
            for s in stars:
                sx, sy, size = s.project()
                if 0 <= sx < W and 0 <= sy < H:
                    _amiga.dot(handle, sx, sy, size, s.pen)

            frame_no += 1
            ev = _amiga.wait_message(handle, 0.03)   # ~30 fps target
            if ev is None:
                continue
            cls = ev["class"]
            if cls == _amiga.IDCMP_CLOSEWINDOW:
                running = False
            elif cls == _amiga.IDCMP_VANILLAKEY and ev["code"] == 27:
                running = False
    finally:
        _amiga.close_window(handle)
        print("starfield: closed", flush=True)


if __name__ == "__main__":
    main()
