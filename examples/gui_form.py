"""gui_form.py — real Intuition UI dialogs from Python.

Uses `RequestChoice` (stock OS4 CLI tool that pops an Intuition
requester) via amiga.intuition.EasyRequest to build a mini
task-runner form:

  1. Confirm you want to proceed
  2. Pick which operation (show tasks / show mem / list windows)
  3. Show a follow-up requester with the result

These are REAL Intuition popups on the Workbench screen — not
simulation.  The event loop of the popup itself is handled by
RequestChoice; we just capture the returned button index.

Run:
    DH1:python-os4 DH1:pytests/examples/gui_form.py
"""
import sys, os
sys.path.insert(0, "DH1:pytests/amiga_bindings")

from amiga import intuition as intu

try:
    import _amiga
    HAVE_NATIVE = True
except ImportError:
    HAVE_NATIVE = False


def show_result(title, body):
    intu.EasyRequest(title=title, body=body, buttons=("OK",))


def op_show_tasks():
    if not HAVE_NATIVE:
        return "native _amiga module not linked — nothing to show"
    tasks = _amiga.list_tasks()
    lines = [f"{len(tasks)} tasks running.  Top 10 by priority:"]
    for name, pri, state in sorted(tasks, key=lambda t: -t[1])[:10]:
        lines.append(f"  {pri:>+4}  {state[:1]}  {name}")
    return "\n".join(lines)


def op_show_memory():
    if not HAVE_NATIVE:
        return "native _amiga module not linked"
    mem = _amiga.avail_mem_summary()
    return (f"Memory free:\n"
            f"  any     {mem['any']:>12,} bytes\n"
            f"  chip    {mem['chip']:>12,} bytes\n"
            f"  fast    {mem['fast']:>12,} bytes\n"
            f"  largest {mem['largest']:>12,} bytes")


def op_show_libs():
    if not HAVE_NATIVE:
        return "native _amiga module not linked"
    libs = _amiga.list_libraries()
    lines = [f"{len(libs)} libraries opened.  Top 8 by open-count:"]
    for name, v, r, oc in sorted(libs, key=lambda l: -l[3])[:8]:
        lines.append(f"  v{v}.{r}  opens={oc}  {name}")
    return "\n".join(lines)


def main():
    # Step 1: confirmation
    proceed = intu.EasyRequest(
        title="Python UI Demo",
        body=("This demo will pop up several Intuition requesters.\n"
              "Each one is a real OS4 window driven from Python.\n\n"
              "Proceed?"),
        buttons=("Yes", "Cancel"))
    if proceed == 0:
        print("user cancelled")
        return

    # Step 2: operation picker
    op = intu.EasyRequest(
        title="Choose operation",
        body="Which system view would you like?",
        buttons=("Tasks", "Memory", "Libraries", "Cancel"))

    if op == 0:
        print("cancelled at operation picker")
        return

    handlers = {1: ("Tasks",     op_show_tasks),
                2: ("Memory",    op_show_memory),
                3: ("Libraries", op_show_libs)}
    title, fn = handlers[op]
    body = fn()

    # Step 3: show the result in a follow-up requester.
    # AmigaDOS shell caps single-arg length ~350 bytes even with proper
    # *n escaping, so chunk aggressively — 6-8 short lines fits nicely.
    lines = body.splitlines()
    MAX_LINES = 8
    for i in range(0, len(lines), MAX_LINES):
        chunk = "\n".join(lines[i:i + MAX_LINES])
        show_result(f"{title} (page {i // MAX_LINES + 1})", chunk)

    print(f"gui_form: shown {title.lower()}, done.")


if __name__ == "__main__":
    main()
