"""planner.py — Python calendar + notes app for AmigaOS 4.

A real productivity app running on real Intuition:

  * Events with title/date/time/attendees/notes/url/tags
  * Free-form notes with title/body/tags
  * SQLite storage at DH1:Documents/Planner/planner.db
  * Tag-based search across events + notes
  * Text-mode UI: main window lists items; menu popups for actions

Data entry today uses a chain of `RequestString` popups (one per
field) — each field is a real Intuition dialog on Workbench.  When
we grow StringGadget support in `_amiga`, the chain becomes a single
composite dialog with no source change to the model/storage.

Run:
    setenv PYTHONHOME DH1: ; setenv PYTHONPATH DH1:lib
    DH1:python-os4 DH1:pytests/examples/planner.py
"""
import os
import sys
import time
import sqlite3
from dataclasses import dataclass, field
from typing import List, Optional

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import amiga.intuition as intu
from amiga.intuition import _dos_quote
from amiga.dos import _run_capture

try:
    import _amiga
    HAVE_INTU = True
except ImportError:
    HAVE_INTU = False


# ---------------------------------------------------------------------------
# Data model + SQLite storage
# ---------------------------------------------------------------------------

DB_DIR = "DH1:Documents/Planner"
DB_PATH = f"{DB_DIR}/planner.db"


@dataclass
class Event:
    id: int = 0
    title: str = ""
    date: str = ""          # YYYY-MM-DD
    time: str = ""          # HH:MM
    attendees: str = ""     # comma-separated
    notes: str = ""
    url: str = ""
    tags: str = ""          # comma-separated
    created: str = ""       # ISO ts

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
    """Thin sqlite3 wrapper — creates DB on first use."""

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
        c.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id        INTEGER PRIMARY KEY,
                title     TEXT NOT NULL,
                date      TEXT NOT NULL,
                time      TEXT,
                attendees TEXT,
                notes     TEXT,
                url       TEXT,
                tags      TEXT,
                created   TEXT
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id        INTEGER PRIMARY KEY,
                title     TEXT NOT NULL,
                body      TEXT,
                tags      TEXT,
                created   TEXT,
                modified  TEXT
            )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_events_tags ON events(tags)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_notes_tags  ON notes(tags)")
        self.conn.commit()

    # -- events ------------------------------------------------------

    def add_event(self, ev: Event) -> int:
        ev.created = time.strftime("%Y-%m-%dT%H:%M:%S")
        c = self.conn.cursor()
        c.execute("""INSERT INTO events
                        (title, date, time, attendees, notes, url, tags, created)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (ev.title, ev.date, ev.time, ev.attendees,
                   ev.notes, ev.url, ev.tags, ev.created))
        self.conn.commit()
        return c.lastrowid

    def list_events(self, limit: int = 100) -> List[Event]:
        c = self.conn.cursor()
        c.execute("SELECT * FROM events ORDER BY date, time LIMIT ?", (limit,))
        return [Event(**dict(r)) for r in c.fetchall()]

    def delete_event(self, eid: int):
        self.conn.execute("DELETE FROM events WHERE id = ?", (eid,))
        self.conn.commit()

    def search_events(self, needle: str) -> List[Event]:
        n = f"%{needle}%"
        c = self.conn.cursor()
        c.execute("""SELECT * FROM events
                     WHERE title    LIKE ? OR notes LIKE ?
                        OR attendees LIKE ? OR tags  LIKE ? OR url LIKE ?
                     ORDER BY date, time""",
                  (n, n, n, n, n))
        return [Event(**dict(r)) for r in c.fetchall()]

    # -- notes -------------------------------------------------------

    def add_note(self, note: Note) -> int:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        note.created = note.modified = now
        c = self.conn.cursor()
        c.execute("""INSERT INTO notes (title, body, tags, created, modified)
                     VALUES (?, ?, ?, ?, ?)""",
                  (note.title, note.body, note.tags, note.created, note.modified))
        self.conn.commit()
        return c.lastrowid

    def list_notes(self, limit: int = 100) -> List[Note]:
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
                     ORDER BY modified DESC""",
                  (n, n, n))
        return [Note(**dict(r)) for r in c.fetchall()]

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# Input helpers — RequestString for single-line, chained for multi-field
# ---------------------------------------------------------------------------

def ask_string(prompt: str, default: str = "", title: str = "Planner") -> Optional[str]:
    """Pop an OS4 RequestString dialog.  Returns entered text, or None if
    the user cancelled."""
    cmd = f"RequestString TITLE {_dos_quote(title)} BODY {_dos_quote(prompt)}"
    if default:
        cmd += f" DEFAULT {_dos_quote(default)}"
    rc, out = _run_capture(cmd)
    if rc != 0:
        return None
    s = out.strip()
    return s if s else None


def ask_menu(title: str, prompt: str, options: list) -> int:
    """Pop RequestChoice with the given button labels; returns index
    (0-based, matches list order — button 0 is rightmost/cancel in
    Amiga convention, but we don't reorder — caller decides)."""
    return intu.EasyRequest(title=title, body=prompt, buttons=tuple(options))


# ---------------------------------------------------------------------------
# Event / Note entry flows
# ---------------------------------------------------------------------------

def new_event(store: Store) -> Optional[Event]:
    """Chain of RequestString popups to gather all event fields."""
    ev = Event()
    ev.title = ask_string("Event title:") or ""
    if not ev.title:
        return None
    ev.date = ask_string("Date (YYYY-MM-DD):",
                         default=time.strftime("%Y-%m-%d")) or ""
    ev.time = ask_string("Time (HH:MM, blank for all-day):",
                         default="09:00") or ""
    ev.attendees = ask_string("Attendees (comma-separated, blank for none):",
                              default="") or ""
    ev.notes = ask_string("Notes (single line for now):", default="") or ""
    ev.url = ask_string("URL (blank for none):", default="") or ""
    ev.tags = ask_string("Tags (comma-separated, blank for none):",
                         default="") or ""
    eid = store.add_event(ev)
    ev.id = eid
    return ev


def new_note(store: Store) -> Optional[Note]:
    n = Note()
    n.title = ask_string("Note title:") or ""
    if not n.title:
        return None
    n.body = ask_string("Body (single line for now):") or ""
    n.tags = ask_string("Tags (comma-separated, blank for none):",
                        default="") or ""
    nid = store.add_note(n)
    n.id = nid
    return n


def view_event(ev: Event) -> str:
    """Return a formatted multi-line description of one event."""
    lines = [
        f"#{ev.id}  {ev.title}",
        f"When:   {ev.date} {ev.time}",
    ]
    if ev.attendees: lines.append(f"With:   {ev.attendees}")
    if ev.notes:     lines.append(f"Notes:  {ev.notes}")
    if ev.url:       lines.append(f"URL:    {ev.url}")
    if ev.tags:      lines.append(f"Tags:   {ev.tags}")
    lines.append(f"Added:  {ev.created}")
    return "\n".join(lines)


def show_event_details(ev: Event):
    """Modal EasyRequest showing full event, with Delete / OK buttons."""
    body = view_event(ev)
    return intu.EasyRequest(title=f"Event #{ev.id}",
                            body=body,
                            buttons=("OK", "Delete"))


# ---------------------------------------------------------------------------
# Main window — event list + menu bar
# ---------------------------------------------------------------------------

def draw_list(handle, events: List[Event], notes: List[Note],
              which: str = "events"):
    """Redraw the main window with a list of events or notes."""
    _amiga.clear_window(handle, 0)
    y, dy = 12, 14
    header = f"=== Python Planner ({which}) ===   "
    header += f"{len(events)} events, {len(notes)} notes"
    _amiga.draw_text(handle, 8, y, header, 2); y += dy * 2

    if which == "events":
        for ev in events[:20]:
            s = f"[{ev.id:3d}] {ev.summary()[:60]}"
            _amiga.draw_text(handle, 8, y, s, 1); y += dy
    else:
        for n in notes[:20]:
            s = f"[{n.id:3d}] {n.title[:60]}"
            _amiga.draw_text(handle, 8, y, s, 1); y += dy

    y += dy
    _amiga.draw_text(handle, 8, y,
        "N=NewEvent  M=NewNote  T=ToggleView  D=Delete  S=Search  Q=Quit",
        3)


def main():
    if not HAVE_INTU:
        print("planner: needs _amiga native module (Phase 6.5+)")
        return

    store = Store()
    print(f"planner: DB at {DB_PATH}")

    handle = _amiga.open_window(
        title="Python Planner",
        left=100, top=60, width=540, height=380,
        idcmp=(_amiga.IDCMP_CLOSEWINDOW
               | _amiga.IDCMP_VANILLAKEY
               | _amiga.IDCMP_REFRESHWINDOW),
    )
    try:
        which = "events"
        while True:
            events = store.list_events()
            notes = store.list_notes()
            draw_list(handle, events, notes, which)

            ev = _amiga.wait_message(handle, -1)   # block forever
            if ev is None:
                continue
            cls = ev["class"]

            if cls == _amiga.IDCMP_CLOSEWINDOW:
                break
            if cls == _amiga.IDCMP_REFRESHWINDOW:
                continue

            if cls == _amiga.IDCMP_VANILLAKEY:
                code = ev["code"]
                ch = chr(code).lower() if 32 <= code < 127 else ""

                if code == 27 or ch == "q":               # ESC / Q
                    break
                elif ch == "n":                            # new event
                    new = new_event(store)
                    if new is not None:
                        intu.EasyRequest(title="Saved",
                                         body=f"Event #{new.id} added:\n{new.title}",
                                         buttons=("OK",))
                elif ch == "m":                            # new note
                    new = new_note(store)
                    if new is not None:
                        intu.EasyRequest(title="Saved",
                                         body=f"Note #{new.id} added:\n{new.title}",
                                         buttons=("OK",))
                elif ch == "t":                            # toggle view
                    which = "notes" if which == "events" else "events"
                elif ch == "d":                            # delete
                    idstr = ask_string(f"Delete {which[:-1]} — ID?")
                    if idstr and idstr.isdigit():
                        did = int(idstr)
                        choice = intu.EasyRequest(
                            title="Confirm",
                            body=f"Really delete {which[:-1]} #{did}?",
                            buttons=("Cancel", "Delete"))
                        if choice == 1:
                            if which == "events":
                                store.delete_event(did)
                            else:
                                store.delete_note(did)
                elif ch == "s":                            # search
                    needle = ask_string("Search text:")
                    if needle:
                        if which == "events":
                            found = store.search_events(needle)
                            body = "\n".join(e.summary()[:60] for e in found[:12]) \
                                   or "(no matches)"
                        else:
                            found = store.search_notes(needle)
                            body = "\n".join(f"{n.id}: {n.title[:50]}"
                                             for n in found[:12]) \
                                   or "(no matches)"
                        intu.EasyRequest(title=f"Results ({len(found)})",
                                         body=body[:340], buttons=("OK",))
    finally:
        _amiga.close_window(handle)
        store.close()
        print("planner: closed cleanly.")


if __name__ == "__main__":
    main()
