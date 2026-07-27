"""prompt_lab.py — showcase every shape of _amiga.open_dialog / run_dialog.

Walks through six dialog variants:

  1. single-line prompt (name)
  2. multi-field record (name / age / email)
  3. long-form (5 fields)
  4. custom button labels (Save / Discard)
  5. OK-only (informational)
  6. tiny narrow prompt (PIN)

After each, prints what the user entered (or "cancelled"). Handy
reference for anyone writing an Intuition-based form and a good
smoke test that the dialog primitive isn't regressed.

Run:
    DH1:python-os4 DH1:pytests/examples/prompt_lab.py
"""
import sys
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga


def ask(title, fields, ok_label="OK", cancel_label="Cancel",
        left=100, top=60):
    """Open a dialog, run it to completion, close, return the dict
    (or None if user cancelled)."""
    h = _amiga.open_dialog(
        title=title, fields=fields,
        ok_label=ok_label, cancel_label=cancel_label,
        left=left, top=top,
    )
    try:
        return _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)


def demo(name, fn):
    print(f"\n=== {name} ===", flush=True)
    result = fn()
    if result is None:
        print("  cancelled.", flush=True)
    else:
        for k, v in result.items():
            print(f"  {k}: {v!r}", flush=True)


def main():
    demo("1. single-line prompt",
         lambda: ask("What's your name?",
                     [("Name", "", 40)]))

    demo("2. multi-field record",
         lambda: ask("Your details",
                     [("Name", "", 40),
                      ("Age", "", 4),
                      ("Email", "you@example.com", 60)]))

    demo("3. long form (5 fields)",
         lambda: ask("New event",
                     [("Title",       "",    60),
                      ("Date",        "",    12),
                      ("Time",        "",     8),
                      ("Attendees",   "",   120),
                      ("Location",    "",    60)]))

    demo("4. custom button labels",
         lambda: ask("Save changes?",
                     [("Filename", "notes.txt", 60)],
                     ok_label="Save", cancel_label="Discard"))

    demo("5. OK-only informational (no cancel)",
         lambda: ask("Notice",
                     [("Message", "Rebuild complete.", 60)],
                     ok_label="OK", cancel_label="OK"))

    demo("6. narrow prompt",
         lambda: ask("PIN",
                     [("Enter PIN", "", 6)],
                     left=200, top=200))

    print("\nprompt_lab: done.", flush=True)


if __name__ == "__main__":
    main()
