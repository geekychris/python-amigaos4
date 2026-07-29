"""planner.py — Python calendar + notes app for AmigaOS 4.

Rich, click-driven UI:

  * **Calendar view** — month grid, click a day → jump to that day
  * **Day view** — hour slots 6-22, existing events in their slot;
    click empty slot → new event pre-filled with date+time;
    click existing event → view/edit dialog
  * **List / Notes views** — flat browsers, click a row to see details
  * Composite Intuition dialog for entry (real StringGadgets)
  * SQLite storage at DH1:Documents/Planner/planner.db
  * Tag/text search across events + notes

Every action reachable by either keyboard hotkey OR mouse click.

Run:
    ; setenv PYTHONHOME python3: ; ; setenv PYTHONPATH python3:lib
    python3 python3:examples/planner.py
"""
import os
import sys
import time
import calendar as pycal
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import _amiga
import amiga.intuition as intu
from amiga.ui import App, Button, ListPanel, Rect, PEN_BG, PEN_FG, PEN_HI, PEN_ACC

HAVE_DIALOG = hasattr(_amiga, "open_dialog")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DB_DIR = "DH1:Documents/Planner" if os.path.exists("DH1:") else "SYS:System/python3/Documents/Planner"
DB_PATH = f"{DB_DIR}/planner.db"


@dataclass
class Event:
    id: int = 0
    title: str = ""
    date: str = ""      # YYYY-MM-DD
    time: str = ""      # HH:MM
    attendees: str = ""
    notes: str = ""
    url: str = ""
    tags: str = ""
    created: str = ""


@dataclass
class Note:
    id: int = 0
    title: str = ""
    body: str = ""
    tags: str = ""
    created: str = ""
    modified: str = ""


class Store:
    def __init__(self, path: str = DB_PATH):
        try:
            os.makedirs(DB_DIR, exist_ok=True)
        except OSError:
            pass
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        c = self.conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                        date TEXT NOT NULL, time TEXT, attendees TEXT,
                        notes TEXT, url TEXT, tags TEXT, created TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS notes (
                        id INTEGER PRIMARY KEY, title TEXT NOT NULL,
                        body TEXT, tags TEXT, created TEXT, modified TEXT)""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)")
        self.conn.commit()

    def add_event(self, ev: Event) -> int:
        ev.created = time.strftime("%Y-%m-%dT%H:%M:%S")
        c = self.conn.cursor()
        c.execute("""INSERT INTO events (title,date,time,attendees,notes,url,tags,created)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (ev.title, ev.date, ev.time, ev.attendees,
                   ev.notes, ev.url, ev.tags, ev.created))
        self.conn.commit()
        return c.lastrowid

    def update_event(self, ev: Event):
        c = self.conn.cursor()
        c.execute("""UPDATE events SET title=?,date=?,time=?,attendees=?,
                                        notes=?,url=?,tags=? WHERE id=?""",
                  (ev.title, ev.date, ev.time, ev.attendees,
                   ev.notes, ev.url, ev.tags, ev.id))
        self.conn.commit()

    def get_event(self, eid: int) -> Optional[Event]:
        r = self.conn.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        return Event(**dict(r)) if r else None

    def list_events(self, limit: int = 200) -> List[Event]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM events ORDER BY date, time LIMIT ?", (limit,))
        return [Event(**dict(r)) for r in c.fetchall()]

    def events_in_month(self, year: int, month: int) -> List[Event]:
        prefix = f"{year:04d}-{month:02d}"
        c = self.conn.cursor()
        c.execute("SELECT * FROM events WHERE date LIKE ? ORDER BY date, time",
                  (f"{prefix}-%",))
        return [Event(**dict(r)) for r in c.fetchall()]

    def events_on(self, date_str: str) -> List[Event]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM events WHERE date = ? ORDER BY time",
                  (date_str,))
        return [Event(**dict(r)) for r in c.fetchall()]

    def delete_event(self, eid: int):
        self.conn.execute("DELETE FROM events WHERE id = ?", (eid,))
        self.conn.commit()

    def search_events(self, needle: str) -> List[Event]:
        n = f"%{needle}%"
        c = self.conn.cursor()
        c.execute("""SELECT * FROM events
                     WHERE title LIKE ? OR notes LIKE ? OR attendees LIKE ?
                        OR tags LIKE ? OR url LIKE ?
                     ORDER BY date, time""", (n, n, n, n, n))
        return [Event(**dict(r)) for r in c.fetchall()]

    def add_note(self, note: Note) -> int:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        note.created = note.modified = now
        c = self.conn.cursor()
        c.execute("""INSERT INTO notes (title,body,tags,created,modified)
                     VALUES (?,?,?,?,?)""",
                  (note.title, note.body, note.tags, note.created, note.modified))
        self.conn.commit()
        return c.lastrowid

    def list_notes(self, limit: int = 200) -> List[Note]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM notes ORDER BY modified DESC LIMIT ?", (limit,))
        return [Note(**dict(r)) for r in c.fetchall()]

    def delete_note(self, nid: int):
        self.conn.execute("DELETE FROM notes WHERE id = ?", (nid,))
        self.conn.commit()

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Dialog wrapper — composite form via _amiga.open_dialog
# ---------------------------------------------------------------------------

def show_form(title, fields, ok="OK", cancel="Cancel"):
    if not HAVE_DIALOG:
        from amiga.dos import _run_capture
        from amiga.intuition import _dos_quote
        result = {}
        for label, default, _maxlen in fields:
            cmd = f"RequestString TITLE {_dos_quote(title)} BODY {_dos_quote(label + ':')}"
            if default:
                cmd += f" DEFAULT {_dos_quote(default)}"
            rc, out = _run_capture(cmd)
            if rc != 0:
                return None
            result[label] = out.strip()
        return result
    h = _amiga.open_dialog(title=title, fields=fields,
                            ok_label=ok, cancel_label=cancel)
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


def event_dialog(existing: Optional[Event] = None) -> Optional[Event]:
    """Composite form for creating OR editing an event."""
    ev = existing or Event()
    today = time.strftime("%Y-%m-%d")
    title = "Edit Event" if existing else "New Event"
    result = show_form(title, [
        ("Title",     ev.title,     120),
        ("Date",      ev.date or today,      12),
        ("Time",      ev.time or "09:00",     8),
        ("Attendees", ev.attendees, 200),
        ("Notes",     ev.notes,     400),
        ("URL",       ev.url,       200),
        ("Tags",      ev.tags,      100),
    ])
    if not result or not result.get("Title", "").strip():
        return None
    ev.title     = result["Title"].strip()
    ev.date      = result.get("Date", today).strip()
    ev.time      = result.get("Time", "").strip()
    ev.attendees = result.get("Attendees", "").strip()
    ev.notes     = result.get("Notes", "").strip()
    ev.url       = result.get("URL", "").strip()
    ev.tags      = result.get("Tags", "").strip()
    return ev


def note_dialog(existing: Optional[Note] = None) -> Optional[Note]:
    n = existing or Note()
    result = show_form("Edit Note" if existing else "New Note", [
        ("Title", n.title, 120),
        ("Body",  n.body,  400),
        ("Tags",  n.tags,  100),
    ])
    if not result or not result.get("Title", "").strip():
        return None
    n.title = result["Title"].strip()
    n.body  = result.get("Body", "").strip()
    n.tags  = result.get("Tags", "").strip()
    return n


# ---------------------------------------------------------------------------
# Planner app state + rendering
# ---------------------------------------------------------------------------

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Calendar cell geometry (populated at draw time so the click hit-test
# can use the same numbers).
CAL_GRID_X0 = 8
CAL_GRID_Y0 = 60
CAL_CELL_W  = 78
CAL_CELL_H  = 44


def draw_menu_bar(app):
    """Top-of-window action bar with clickable buttons + text hints."""
    app.text(8, 14, f"=== Python Planner ===   view: {app.state['view']}", PEN_HI)


def draw_calendar(app, store, year, month, today):
    app.clear()
    draw_menu_bar(app)
    app.text(8, 32,
             f"{MONTHS[month-1]} {year}   "
             "[< prev]  [> next]   click a day for hour view   "
             "L=list  M=notes  N=new  S=search  Q=quit", PEN_FG)

    # Day-of-week header row
    for i, wd in enumerate(WEEKDAYS):
        app.text(CAL_GRID_X0 + i * CAL_CELL_W + 4, CAL_GRID_Y0 + 12, wd, PEN_ACC)

    grid_y = CAL_GRID_Y0 + 20

    # Which days have events?
    events = store.events_in_month(year, month)
    days_with_events = {}
    for ev in events:
        try:
            d = int(ev.date.split("-")[2])
        except (IndexError, ValueError):
            continue
        days_with_events.setdefault(d, []).append(ev)

    cal = pycal.Calendar(firstweekday=0)
    for week_idx, week in enumerate(cal.monthdayscalendar(year, month)):
        row_y = grid_y + week_idx * CAL_CELL_H
        for col_idx, day in enumerate(week):
            x = CAL_GRID_X0 + col_idx * CAL_CELL_W
            # Cell border
            app.line(x, row_y, x + CAL_CELL_W, row_y, PEN_FG)
            app.line(x, row_y, x, row_y + CAL_CELL_H, PEN_FG)
            if day == 0:
                continue
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            is_today = (date_str == today)
            has_evts = day in days_with_events
            if is_today:
                app.fill(x + 1, row_y + 1, x + CAL_CELL_W - 1, row_y + 14,
                          PEN_ACC)
                pen = PEN_HI
            else:
                pen = PEN_FG
            app.text(x + 4, row_y + 12, f"{day:2d}", pen)
            if has_evts:
                app.text(x + 4, row_y + 26,
                          f"{len(days_with_events[day])} evts", PEN_ACC)
                app.text(x + 4, row_y + 38,
                          days_with_events[day][0].title[:9], PEN_FG)

    last_x = CAL_GRID_X0 + 7 * CAL_CELL_W
    app.line(last_x, grid_y, last_x, grid_y + 6 * CAL_CELL_H, PEN_FG)
    app.line(CAL_GRID_X0, grid_y + 6 * CAL_CELL_H,
              last_x,     grid_y + 6 * CAL_CELL_H, PEN_FG)


def hit_test_calendar(x, y, year, month):
    """Return (year, month, day) or None if the click isn't on a day cell."""
    grid_y = CAL_GRID_Y0 + 20
    if y < grid_y or x < CAL_GRID_X0:
        return None
    col = (x - CAL_GRID_X0) // CAL_CELL_W
    row = (y - grid_y) // CAL_CELL_H
    if not (0 <= col < 7 and 0 <= row < 6):
        return None
    cal = pycal.Calendar(firstweekday=0)
    weeks = cal.monthdayscalendar(year, month)
    if row >= len(weeks):
        return None
    day = weeks[row][col]
    if day == 0:
        return None
    return (year, month, day)


# --- day view (hour by hour) ------------------------------------------------

DAY_START_HOUR = 6      # 06:00
DAY_END_HOUR   = 23     # 23:00 (last row = 22:00-23:00 slot)
DAY_ROW_H      = 16
DAY_HOUR_X     = 40     # x where the "HH:00" label ends


def draw_day_view(app, store, y, m, d):
    app.clear()
    draw_menu_bar(app)
    date_str = f"{y:04d}-{m:02d}-{d:02d}"
    weekday = pycal.day_name[pycal.weekday(y, m, d)]
    app.text(8, 32,
             f"{weekday}  {MONTHS[m-1]} {d}, {y}   [c] back to calendar   "
             "click an empty hour to add · click an event to edit", PEN_FG)

    events_by_hour = {}
    on_day = store.events_on(date_str)
    for e in on_day:
        try:
            hh = int((e.time or "0:0").split(":")[0])
        except ValueError:
            hh = 0
        events_by_hour.setdefault(hh, []).append(e)

    y0 = 60
    for i, hh in enumerate(range(DAY_START_HOUR, DAY_END_HOUR + 1)):
        row_y = y0 + i * DAY_ROW_H
        # background stripe on even rows for readability
        if i % 2 == 0:
            app.fill(8, row_y, 550, row_y + DAY_ROW_H - 1, PEN_BG)
        app.text(8, row_y + DAY_ROW_H - 3, f"{hh:02d}:00", PEN_ACC)
        # separator line
        app.line(DAY_HOUR_X, row_y, 550, row_y, PEN_FG)
        # events in this hour
        evts = events_by_hour.get(hh, [])
        for j, e in enumerate(evts):
            x = DAY_HOUR_X + 6 + j * 180
            if x + 175 > 550:
                break
            # highlight box
            app.fill(x, row_y + 1, x + 175, row_y + DAY_ROW_H - 2, PEN_ACC)
            app.text(x + 3, row_y + DAY_ROW_H - 3,
                      f"[{e.id}] {e.title[:20]}", PEN_HI)
    # bottom border
    end_y = y0 + (DAY_END_HOUR - DAY_START_HOUR + 1) * DAY_ROW_H
    app.line(8, end_y, 550, end_y, PEN_FG)


def hit_test_day_view(x, y, store, date_str):
    """Return ("hour", hh) if empty hour, ("event", event_id) if clicked
    an event, or None."""
    y0 = 60
    end_y = y0 + (DAY_END_HOUR - DAY_START_HOUR + 1) * DAY_ROW_H
    if y < y0 or y > end_y or x < 8 or x > 550:
        return None
    i = (y - y0) // DAY_ROW_H
    hh = DAY_START_HOUR + i
    if hh > DAY_END_HOUR:
        return None
    # Was the click on an event box?
    on_day = store.events_on(date_str)
    for e in on_day:
        try:
            e_hh = int((e.time or "0:0").split(":")[0])
        except ValueError:
            e_hh = 0
        if e_hh != hh:
            continue
        # find its slot index (same order as draw)
        siblings = [ev for ev in on_day if ev.time.startswith(f"{hh:02d}:")]
        for j, sib in enumerate(siblings):
            slot_x = DAY_HOUR_X + 6 + j * 180
            if slot_x <= x <= slot_x + 175 and sib.id == e.id:
                return ("event", e.id)
    return ("hour", hh)


# --- list / notes views (also clickable) -----------------------------------

def build_list_view(app, store, kind):
    """Populate app.widgets with a ListPanel + a small button row."""
    if kind == "notes":
        items = store.list_notes()
        rows = [f"[{n.id:3d}] {n.title[:60]}" for n in items]
    else:
        items = store.list_events()
        rows = [f"[{ev.id:3d}] {ev.date} {ev.time:5s} {ev.title[:50]}" for ev in items]

    def on_pick(a, idx, _text):
        obj = items[idx]
        if kind == "notes":
            body = f"{obj.title}\n\n{obj.body[:200]}\n\nTags: {obj.tags}"
            intu.EasyRequest(title=f"Note #{obj.id}", body=body[:340],
                             buttons=("OK",))
        else:
            body = event_summary(obj)
            choice = intu.EasyRequest(title=f"Event #{obj.id}", body=body[:340],
                                      buttons=("OK", "Edit", "Delete"))
            if choice == 1:      # Edit
                new = event_dialog(obj)
                if new is not None:
                    store.update_event(new)
                    a.state["needs_refresh"] = True
            elif choice == 2:    # Delete
                store.delete_event(obj.id)
                a.state["needs_refresh"] = True

    lp = ListPanel(Rect(8, 60, 550, 340), items=rows, on_pick=on_pick,
                    row_h=14)
    app.widgets = [lp]


def event_summary(ev: Event) -> str:
    lines = [ev.title, "", f"When:   {ev.date} {ev.time}"]
    if ev.attendees: lines.append(f"With:   {ev.attendees}")
    if ev.notes:     lines.append(f"Notes:  {ev.notes[:120]}")
    if ev.url:       lines.append(f"URL:    {ev.url}")
    if ev.tags:      lines.append(f"Tags:   {ev.tags}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------

def main():
    store = Store()
    print(f"planner: DB at {DB_PATH}")

    now = time.localtime()
    today = time.strftime("%Y-%m-%d")

    app = App(title="Python Planner", w=560, h=380, left=100, top=40)
    app.state = {
        "view": "calendar",
        "year": now.tm_year,
        "month": now.tm_mon,
        "day": now.tm_mday,
        "needs_refresh": False,
    }

    # -- redraw --------------------------------------------------------
    def redraw(a):
        v = a.state["view"]
        if v == "calendar":
            a.widgets = []
            draw_calendar(a, store, a.state["year"], a.state["month"], today)
        elif v == "day":
            a.widgets = []
            draw_day_view(a, store,
                          a.state["year"], a.state["month"], a.state["day"])
        elif v in ("list", "notes"):
            build_list_view(a, store, v)
            a.clear()
            draw_menu_bar(a)
            a.text(8, 32,
                    f"{v.title()}   [C=calendar]  [L=list]  [M=notes]  "
                    "[N=new]  click a row to see details", PEN_FG)
            a.draw_widgets()
    app.redraw = redraw

    # -- click routing -------------------------------------------------
    def on_click(a, x, y):
        v = a.state["view"]
        if v == "calendar":
            hit = hit_test_calendar(x, y, a.state["year"], a.state["month"])
            if hit:
                a.state["year"], a.state["month"], a.state["day"] = hit
                a.state["view"] = "day"
                return True
        elif v == "day":
            date_str = f"{a.state['year']:04d}-{a.state['month']:02d}-{a.state['day']:02d}"
            hit = hit_test_day_view(x, y, store, date_str)
            if hit is None:
                return False
            kind, val = hit
            if kind == "hour":
                # New event at this hour
                ev = Event(date=date_str, time=f"{val:02d}:00")
                new = event_dialog(ev)
                if new is not None:
                    store.add_event(new)
                return True
            elif kind == "event":
                existing = store.get_event(val)
                if existing is not None:
                    choice = intu.EasyRequest(title=f"Event #{existing.id}",
                        body=event_summary(existing)[:340],
                        buttons=("OK", "Edit", "Delete"))
                    if choice == 1:
                        new = event_dialog(existing)
                        if new is not None:
                            store.update_event(new)
                    elif choice == 2:
                        store.delete_event(existing.id)
                return True
        # list / notes: widget's on_pick handles it
        return False
    app.on_click = on_click

    # -- keyboard hotkeys ---------------------------------------------
    def on_key(a, ch, code):
        if code == 27 or ch == "q":
            a.stop()
            return False
        if ch == "c":
            a.state["view"] = "calendar"
            return True
        if ch == "l":
            a.state["view"] = "list"
            return True
        if ch == "m":
            a.state["view"] = "notes"
            return True
        if ch == "n":
            date_str = f"{a.state['year']:04d}-{a.state['month']:02d}-{a.state['day']:02d}"
            ev = Event(date=date_str, time="09:00")
            new = event_dialog(ev)
            if new is not None:
                store.add_event(new)
                return True
        if ch == "o":
            new = note_dialog()
            if new is not None:
                store.add_note(new)
                return True
        if ch == "s":
            r = show_form("Search", [("Query", "", 100)])
            if r and r.get("Query", "").strip():
                needle = r["Query"].strip()
                found = store.search_events(needle)
                body = "\n".join(f"{e.date} {e.time} {e.title[:40]}"
                                 for e in found[:12]) or "(no matches)"
                intu.EasyRequest(title=f"Results ({len(found)})",
                                 body=body[:340], buttons=("OK",))
                return True
        if ch in "<,":
            if a.state["view"] == "calendar":
                a.state["month"] -= 1
                if a.state["month"] < 1:
                    a.state["month"] = 12; a.state["year"] -= 1
                return True
            elif a.state["view"] == "day":
                # prev day
                y, m, d = a.state["year"], a.state["month"], a.state["day"]
                d -= 1
                if d < 1:
                    m -= 1
                    if m < 1:
                        m = 12; y -= 1
                    d = pycal.monthrange(y, m)[1]
                a.state["year"], a.state["month"], a.state["day"] = y, m, d
                return True
        if ch in ">.":
            if a.state["view"] == "calendar":
                a.state["month"] += 1
                if a.state["month"] > 12:
                    a.state["month"] = 1; a.state["year"] += 1
                return True
            elif a.state["view"] == "day":
                y, m, d = a.state["year"], a.state["month"], a.state["day"]
                last = pycal.monthrange(y, m)[1]
                d += 1
                if d > last:
                    d = 1; m += 1
                    if m > 12:
                        m = 1; y += 1
                a.state["year"], a.state["month"], a.state["day"] = y, m, d
                return True
        if ch == "?":
            intu.EasyRequest(title="Planner help",
                body=("Calendar view: click a day → hour view\n"
                      "Day view:      click empty hour → new event\n"
                      "               click event → view / edit / delete\n"
                      "Hotkeys: C=cal L=list M=notes N=new O=newNote\n"
                      "         < > = prev/next  S=search Q=quit"),
                buttons=("OK",))
            return True
        return False
    app.on_key = on_key

    def on_closed(a):
        store.close()
        print("planner: closed cleanly.")
    app.on_closed = on_closed

    app.run()


if __name__ == "__main__":
    main()
