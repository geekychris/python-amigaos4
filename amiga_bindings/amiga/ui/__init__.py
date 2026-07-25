"""
amiga.ui — higher-level UI primitives on top of `_amiga`.

Where `amiga.intuition` gives you the raw Window/IDCMP paradigm and
`_amiga.open_dialog` gives you a composite form, this module lets you
build click-driven, panel-oriented apps in a few lines:

  * `Button(x, y, w, h, label, on_click)`   — clickable rectangle with text
  * `Rect(x1, y1, x2, y2)`                  — hit-test helper
  * `ListPanel(x, y, w, h, items, ...)`     — scrollable list with selected-row highlight
  * `App(title, w, h, layout_fn, ...)`      — main event loop:
        opens the window, dispatches VANILLAKEY / MOUSEBUTTONS / CLOSEWINDOW
        to registered handlers.  `layout_fn(app)` is called to (re)draw.

Every widget is a plain dict/dataclass — no ownership of the window,
just a hit-test rectangle + draw callback + click callback.  The App
owns the window handle and passes it to draw calls.

Zero widgets do their own I/O — the App's event loop is the single
source of truth.  This keeps things predictable and lets you compose
apps that mix keyboard-driven + click-driven flows without racing.
"""
import time

try:
    import _amiga
except ImportError:
    raise ImportError("amiga.ui requires the _amiga native module")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Intuition mouse button codes (from IECODE_*)
SELECTDOWN = 0x68
SELECTUP   = 0xE8   # SELECTDOWN | IECODE_UP_PREFIX (0x80)
MENUDOWN   = 0x69
MENUUP     = 0xE9

# Common pen indices on Workbench 3.x/4.x default palette
PEN_BG    = 0    # background grey
PEN_FG    = 1    # foreground text (black)
PEN_HI    = 2    # highlight (usually white)
PEN_ACC   = 3    # accent (usually blue)


class Rect:
    """Axis-aligned rectangle in window inner coords."""
    __slots__ = ("x1", "y1", "x2", "y2")

    def __init__(self, x1, y1, x2, y2):
        self.x1, self.y1 = int(x1), int(y1)
        self.x2, self.y2 = int(x2), int(y2)

    def contains(self, x, y):
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2

    def w(self):  return self.x2 - self.x1
    def h(self):  return self.y2 - self.y1


# ---------------------------------------------------------------------------
# Widgets — each is data + a draw method + optional click handler
# ---------------------------------------------------------------------------

class Widget:
    """Base class.  Subclasses override draw() and (optionally) click()."""
    def __init__(self, rect):
        self.rect = rect

    def draw(self, handle):
        pass

    def click(self, app, x, y):
        return False    # True if the click was handled (event consumed)


class Button(Widget):
    def __init__(self, rect, label, on_click=None,
                 pen_border=PEN_FG, pen_text=PEN_FG, pen_bg=PEN_BG):
        super().__init__(rect)
        self.label = label
        self.on_click = on_click
        self.pen_border = pen_border
        self.pen_text = pen_text
        self.pen_bg = pen_bg

    def draw(self, handle):
        r = self.rect
        _amiga.fill_rect(handle, r.x1, r.y1, r.x2, r.y2, self.pen_bg)
        _amiga.draw_line(handle, r.x1, r.y1, r.x2, r.y1, self.pen_border)
        _amiga.draw_line(handle, r.x1, r.y2, r.x2, r.y2, self.pen_border)
        _amiga.draw_line(handle, r.x1, r.y1, r.x1, r.y2, self.pen_border)
        _amiga.draw_line(handle, r.x2, r.y1, r.x2, r.y2, self.pen_border)
        # crude text centering (assume 6px per char for topaz.font)
        text_x = r.x1 + max(3, (r.w() - len(self.label) * 8) // 2)
        text_y = r.y1 + r.h() // 2 + 4
        _amiga.draw_text(handle, text_x, text_y, self.label, self.pen_text)

    def click(self, app, x, y):
        if not self.rect.contains(x, y):
            return False
        if self.on_click:
            self.on_click(app)
        return True


class Label(Widget):
    """Static text at a position.  No click behaviour."""
    def __init__(self, x, y, text, pen=PEN_FG):
        super().__init__(Rect(x, y, x + max(1, len(text) * 8), y + 12))
        self.text = text
        self.pen = pen

    def draw(self, handle):
        _amiga.draw_text(handle, self.rect.x1, self.rect.y1 + 10,
                          self.text, self.pen)


class ListPanel(Widget):
    """Scrollable list of strings with selected-row highlight.

    on_pick(app, index, item) fires on click.
    Set .selected = i externally to preselect / update after data changes.
    """
    def __init__(self, rect, items=None, on_pick=None, row_h=14,
                 pen_text=PEN_FG, pen_selected_bg=PEN_ACC,
                 pen_selected_text=PEN_HI):
        super().__init__(rect)
        self.items = items or []
        self.on_pick = on_pick
        self.row_h = row_h
        self.selected = -1
        self.top = 0    # scroll offset
        self.pen_text = pen_text
        self.pen_selected_bg = pen_selected_bg
        self.pen_selected_text = pen_selected_text

    def visible_rows(self):
        return max(1, self.rect.h() // self.row_h)

    def draw(self, handle):
        r = self.rect
        # Frame
        _amiga.fill_rect(handle, r.x1, r.y1, r.x2, r.y2, PEN_BG)
        _amiga.draw_line(handle, r.x1, r.y1, r.x2, r.y1, PEN_FG)
        _amiga.draw_line(handle, r.x1, r.y2, r.x2, r.y2, PEN_FG)
        _amiga.draw_line(handle, r.x1, r.y1, r.x1, r.y2, PEN_FG)
        _amiga.draw_line(handle, r.x2, r.y1, r.x2, r.y2, PEN_FG)

        n_visible = self.visible_rows()
        for i in range(n_visible):
            idx = self.top + i
            if idx >= len(self.items):
                break
            row_y = r.y1 + i * self.row_h + 2
            if idx == self.selected:
                _amiga.fill_rect(handle, r.x1 + 1, row_y,
                                  r.x2 - 1, row_y + self.row_h - 1,
                                  self.pen_selected_bg)
                pen = self.pen_selected_text
            else:
                pen = self.pen_text
            text = str(self.items[idx])
            # crude truncation
            max_chars = max(1, (r.w() - 8) // 8)
            if len(text) > max_chars:
                text = text[:max_chars]
            _amiga.draw_text(handle, r.x1 + 4, row_y + self.row_h - 3,
                              text, pen)

    def click(self, app, x, y):
        if not self.rect.contains(x, y):
            return False
        row = (y - self.rect.y1) // self.row_h
        idx = self.top + row
        if 0 <= idx < len(self.items):
            self.selected = idx
            if self.on_pick:
                self.on_pick(app, idx, self.items[idx])
        return True

    def scroll_by(self, delta):
        self.top = max(0, min(len(self.items) - 1, self.top + delta))


# ---------------------------------------------------------------------------
# App — the event loop + widget dispatch
# ---------------------------------------------------------------------------

class App:
    """Owns a Window handle + a widget list + a redraw callback.

    Typical usage:

        app = App("My App", w=560, h=400,
                  idcmp=(_amiga.IDCMP_CLOSEWINDOW | _amiga.IDCMP_VANILLAKEY
                         | _amiga.IDCMP_MOUSEBUTTONS
                         | _amiga.IDCMP_REFRESHWINDOW))

        def redraw(app):
            app.clear()
            app.draw_widgets()   # or draw custom stuff first

        app.redraw = redraw
        app.on_key = lambda a, ch, code: ...
        app.widgets = [Button(...), ListPanel(...)]
        app.run()
    """

    def __init__(self, title, w=560, h=400, left=100, top=40, idcmp=None):
        if idcmp is None:
            idcmp = (_amiga.IDCMP_CLOSEWINDOW
                     | _amiga.IDCMP_VANILLAKEY
                     | _amiga.IDCMP_MOUSEBUTTONS
                     | _amiga.IDCMP_REFRESHWINDOW)
        self.handle = _amiga.open_window(
            title=title, left=left, top=top, width=w, height=h, idcmp=idcmp)
        self.widgets = []            # list of Widget subclasses
        self.state = {}              # free-form app state
        self.redraw = lambda app: app.draw_widgets()
        self.on_key = None           # def on_key(app, ch, code)
        self.on_click = None         # def on_click(app, x, y)  — called BEFORE widget dispatch
        self.on_closed = None        # def on_closed(app)
        self._running = True

    # -- drawing --------------------------------------------------------

    def clear(self, pen=PEN_BG):
        _amiga.clear_window(self.handle, pen)

    def text(self, x, y, s, pen=PEN_FG):
        _amiga.draw_text(self.handle, x, y, s, pen)

    def line(self, x1, y1, x2, y2, pen=PEN_FG):
        _amiga.draw_line(self.handle, x1, y1, x2, y2, pen)

    def fill(self, x1, y1, x2, y2, pen):
        _amiga.fill_rect(self.handle, x1, y1, x2, y2, pen)

    def draw_widgets(self):
        for w in self.widgets:
            w.draw(self.handle)

    def request_redraw(self):
        self.redraw(self)

    # -- lifecycle ------------------------------------------------------

    def close(self):
        if self.handle:
            try:
                _amiga.close_window(self.handle)
            except Exception:
                pass
            self.handle = None
        if self.on_closed:
            try:
                self.on_closed(self)
            except Exception:
                pass

    def stop(self):
        self._running = False

    def run(self):
        self.request_redraw()
        try:
            while self._running:
                ev = _amiga.wait_message(self.handle, -1)
                if ev is None:
                    continue
                cls = ev["class"]

                if cls == _amiga.IDCMP_CLOSEWINDOW:
                    break
                if cls == _amiga.IDCMP_REFRESHWINDOW:
                    self.request_redraw()
                    continue

                if cls == _amiga.IDCMP_VANILLAKEY:
                    code = ev["code"]
                    ch = chr(code).lower() if 32 <= code < 127 else ""
                    if code == 27:
                        break
                    if self.on_key:
                        try:
                            if self.on_key(self, ch, code):
                                self.request_redraw()
                        except Exception as e:
                            print(f"[amiga.ui] on_key raised: {e}")

                elif cls == _amiga.IDCMP_MOUSEBUTTONS:
                    if ev["code"] != SELECTDOWN:
                        continue
                    x, y = ev["mouse_x"], ev["mouse_y"]
                    handled = False
                    if self.on_click:
                        try:
                            handled = bool(self.on_click(self, x, y))
                        except Exception as e:
                            print(f"[amiga.ui] on_click raised: {e}")
                    if not handled:
                        for w in self.widgets:
                            if w.click(self, x, y):
                                handled = True
                                break
                    if handled:
                        self.request_redraw()
        finally:
            self.close()
