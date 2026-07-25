"""planner.py — Python calendar + notes app for AmigaOS 4.

Real productivity app running on real Intuition:

  * **Calendar view** — month grid with days-having-events highlighted
  * **List view** — flat event/notes browser sortable by date
  * Events: title, date, time, attendees, notes, url, tags
  * Notes: title, body, tags
  * **One composite dialog per record** — proper StringGadgets, no
    RequestString-chain wizard
  * SQLite at DH1:Documents/Planner/planner.db
  * Tag/text search across everything

Views:
  C   calendar grid (default)
  L   list view (events)
  M   notes view
  <>  prev / next month in calendar view
  N   new event  (composite dialog)
  O   new note   (composite dialog)
  D   delete
  S   search
  ESC/Q  quit

Run:
    setenv PYTHONHOME DH1: ; setenv PYTHONPATH DH1:lib
    DH1:python-os4 DH1:pytests/examples/planner.py
"""
import os
import sys
import time
import calendar as pycal
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import amiga.intuition as intu

try:
    import _amiga
    HAVE_NATIVE = True
except ImportError:
    HAVE_NATIVE = False

HAVE_DIALOG = HAVE_NATIVE and hasattr(_amiga, "open_dialog")


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

DB_DIR = "DH1:Documents/Planner"
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

    def summary(self) -> str:
        return f"{self.date} {self.time}  {self.title}"


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

    def search_notes(self, needle: str) -> List[Note]:
        n = f"%{needle}%"
        c = self.conn.cursor()
        c.execute("""SELECT * FROM notes
                     WHERE title LIKE ? OR body LIKE ? OR tags LIKE ?
                     ORDER BY modified DESC""", (n, n, n))
        return [Note(**dict(r)) for r in c.fetchall()]

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Dialogs — new composite form via _amiga.open_dialog, wizard fallback
# ---------------------------------------------------------------------------

def show_form(title: str, fields, ok="OK", cancel="Cancel"):
    """Wrapper around _amiga.open_dialog + run_dialog + close_dialog.
    `fields` is a list of (label, default, maxlen).  Returns dict of
    label→text on OK, None on Cancel."""
    if not HAVE_DIALOG:
        # Fall back to RequestString chain — see planner_wizard for details.
        from amiga.dos import _run_capture
        from amiga.intuition import _dos_quote
        result = {}
        for label, default, _maxlen in fields:
            cmd = (f"RequestString TITLE {_dos_quote(title)} "
                   f"BODY {_dos_quote(label + ':')}")
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


def new_event_form(store: Store) -> Optional[Event]:
    today = time.strftime("%Y-%m-%d")
    result = show_form("New Event", [
        ("Title",     "",     120),
        ("Date",      today,   12),
        ("Time",      "09:00",  8),
        ("Attendees", "",     200),
        ("Notes",     "",     400),
        ("URL",       "",     200),
        ("Tags",      "",     100),
    ])
    if not result or not result.get("Title", "").strip():
        return None
    ev = Event(
        title=result["Title"].strip(),
        date=result.get("Date", today).strip(),
        time=result.get("Time", "").strip(),
        attendees=result.get("Attendees", "").strip(),
        notes=result.get("Notes", "").strip(),
        url=result.get("URL", "").strip(),
        tags=result.get("Tags", "").strip(),
    )
    ev.id = store.add_event(ev)
    return ev


def new_note_form(store: Store) -> Optional[Note]:
    result = show_form("New Note", [
        ("Title", "", 120),
        ("Body",  "", 400),
        ("Tags",  "", 100),
    ])
    if not result or not result.get("Title", "").strip():
        return None
    n = Note(title=result["Title"].strip(),
             body=result.get("Body", "").strip(),
             tags=result.get("Tags", "").strip())
    n.id = store.add_note(n)
    return n


# ---------------------------------------------------------------------------
# Views — calendar grid, list, notes
# ---------------------------------------------------------------------------

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def draw_calendar(handle, store: Store, year: int, month: int, today: str):
    _amiga.clear_window(handle, 0)
    # Header
    _amiga.draw_text(handle, 8, 14,
        f"=== Python Planner ===   {MONTHS[month-1]} {year}   "
        f"(< prev  > next month  C=cal L=list M=notes N=new  ?=help)", 2)

    # Day-of-week header row
    cell_w, cell_h = 74, 42
    grid_x0, grid_y0 = 8, 40
    for i, wd in enumerate(WEEKDAYS):
        _amiga.draw_text(handle, grid_x0 + i * cell_w + 4,
                         grid_y0 + 12, wd, 3)

    grid_y0 += 20

    # Which days have events?
    events = store.events_in_month(year, month)
    days_with_events = {}
    for ev in events:
        try:
            d = int(ev.date.split("-")[2])
        except (IndexError, ValueError):
            continue
        days_with_events.setdefault(d, []).append(ev)

    # Draw grid
    cal = pycal.Calendar(firstweekday=0)   # Monday
    for week_idx, week in enumerate(cal.monthdayscalendar(year, month)):
        row_y = grid_y0 + week_idx * cell_h
        for col_idx, day in enumerate(week):
            x = grid_x0 + col_idx * cell_w
            # Cell border
            _amiga.draw_line(handle, x, row_y, x + cell_w, row_y, 1)
            _amiga.draw_line(handle, x, row_y, x, row_y + cell_h, 1)
            if day == 0:
                continue
            date_str = f"{year:04d}-{month:02d}-{day:02d}"
            is_today = date_str == today
            has_events = day in days_with_events
            pen = 3 if is_today else (2 if has_events else 1)
            _amiga.draw_text(handle, x + 4, row_y + 12, f"{day:2d}", pen)
            if has_events:
                # Count + brief preview
                evs = days_with_events[day]
                _amiga.draw_text(handle, x + 4, row_y + 24,
                                 f"{len(evs)} evt", 2)
                _amiga.draw_text(handle, x + 4, row_y + 36,
                                 evs[0].title[:9], 1)

    # Right-side border of last column
    last_x = grid_x0 + 7 * cell_w
    _amiga.draw_line(handle, last_x, grid_y0,
                     last_x, grid_y0 + 6 * cell_h, 1)
    # Bottom border
    _amiga.draw_line(handle, grid_x0, grid_y0 + 6 * cell_h,
                     last_x, grid_y0 + 6 * cell_h, 1)


def draw_list(handle, events: List[Event], notes: List[Note], view: str):
    _amiga.clear_window(handle, 0)
    y, dy = 14, 14
    _amiga.draw_text(handle, 8, y,
        f"=== Python Planner ({view}) ===   "
        f"{len(events)} events, {len(notes)} notes", 2); y += dy * 2

    if view == "events":
        for ev in events[:20]:
            _amiga.draw_text(handle, 8, y,
                f"[{ev.id:3d}] {ev.summary()[:66]}", 1); y += dy
    else:
        for n in notes[:20]:
            _amiga.draw_text(handle, 8, y,
                f"[{n.id:3d}] {n.title[:66]}", 1); y += dy

    y += dy
    _amiga.draw_text(handle, 8, y,
        "N=new event  O=new note  C=calendar  L=list  M=notes  "
        "D=delete  S=search  Q=quit", 3)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not HAVE_NATIVE:
        print("planner: needs _amiga native module")
        return
    if not HAVE_DIALOG:
        print("planner: _amiga.open_dialog not present — will fall back to "
              "RequestString wizard.  Upgrade python-os4 for composite form.")

    store = Store()
    print(f"planner: DB at {DB_PATH}")

    now = time.localtime()
    cur_year, cur_month = now.tm_year, now.tm_mon
    today = time.strftime("%Y-%m-%d")
    view = "calendar"

    handle = _amiga.open_window(
        title="Python Planner",
        left=100, top=40, width=560, height=380,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_REFRESHWINDOW),
    )
    try:
        while True:
            if view == "calendar":
                draw_calendar(handle, store, cur_year, cur_month, today)
            elif view == "notes":
                draw_list(handle, store.list_events(), store.list_notes(), "notes")
            else:
                draw_list(handle, store.list_events(), store.list_notes(), "events")

            ev = _amiga.wait_message(handle, -1)
            if ev is None:
                continue
            cls = ev["class"]

            if cls == _amiga.IDCMP_CLOSEWINDOW:
                break
            if cls == _amiga.IDCMP_REFRESHWINDOW:
                continue
            if cls != _amiga.IDCMP_VANILLAKEY:
                continue

            code = ev["code"]
            ch = chr(code).lower() if 32 <= code < 127 else ""

            if code == 27 or ch == "q":
                break

            elif ch == "n":                      # new event
                new = new_event_form(store)
                if new is not None:
                    intu.EasyRequest(title="Saved",
                        body=f"Event #{new.id} added:\n{new.title[:80]}",
                        buttons=("OK",))
            elif ch == "o":                      # new note
                new = new_note_form(store)
                if new is not None:
                    intu.EasyRequest(title="Saved",
                        body=f"Note #{new.id} added:\n{new.title[:80]}",
                        buttons=("OK",))
            elif ch == "c":
                view = "calendar"
            elif ch == "l":
                view = "list"
            elif ch == "m":
                view = "notes"
            elif ch == "<" or ch == ",":         # prev month
                if view == "calendar":
                    cur_month -= 1
                    if cur_month < 1:
                        cur_month = 12; cur_year -= 1
            elif ch == ">" or ch == ".":         # next month
                if view == "calendar":
                    cur_month += 1
                    if cur_month > 12:
                        cur_month = 1; cur_year += 1
            elif ch == "d":                      # delete
                target = "event" if view != "notes" else "note"
                r = show_form(f"Delete {target}", [("ID", "", 8)])
                if r and r.get("ID", "").strip().isdigit():
                    did = int(r["ID"])
                    if intu.EasyRequest(title="Confirm",
                            body=f"Really delete {target} #{did}?",
                            buttons=("Cancel", "Delete")) == 1:
                        if target == "event":
                            store.delete_event(did)
                        else:
                            store.delete_note(did)
            elif ch == "s":                      # search
                r = show_form("Search", [("Query", "", 100)])
                if r and r.get("Query", "").strip():
                    needle = r["Query"].strip()
                    if view == "notes":
                        found = store.search_notes(needle)
                        body = "\n".join(f"{n.id}: {n.title[:50]}"
                                         for n in found[:10]) or "(no matches)"
                    else:
                        found = store.search_events(needle)
                        body = "\n".join(e.summary()[:60]
                                         for e in found[:10]) or "(no matches)"
                    intu.EasyRequest(title=f"Results ({len(found)})",
                                     body=body[:340], buttons=("OK",))
            elif ch == "?":
                intu.EasyRequest(title="Planner help",
                    body=("N=new event    O=new note\n"
                          "C=calendar     L=list      M=notes\n"
                          "< > = prev/next month  (calendar view)\n"
                          "D=delete       S=search    Q/ESC=quit"),
                    buttons=("OK",))
    finally:
        _amiga.close_window(handle)
        store.close()
        print("planner: closed cleanly.")


if __name__ == "__main__":
    main()
