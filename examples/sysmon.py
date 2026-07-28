"""sysmon.py — live AmigaOS 4 system monitor in Python.

Uses the native _amiga module (Phase 6) to introspect the running
system every 2 seconds:

  - free memory (any / chip / fast / largest)
  - task count grouped by state (Ready / Wait)
  - top 8 tasks by priority
  - opened libraries (top 8 by open-count)
  - public message ports

Prints a full-screen refresh with an ANSI clear so the output stays
readable in an Amiga CLI window.  Ctrl-C exits cleanly.

Run:
    python3 python3:examples/sysmon.py [interval_seconds]
"""
import sys, os
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import time
import _amiga


CLEAR = "\x1b[2J\x1b[H"      # ANSI clear + home cursor
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def fmt_bytes(b):
    if b > 1_073_741_824:
        return f"{b / 1_073_741_824:6.2f} GB"
    if b > 1_048_576:
        return f"{b / 1_048_576:6.1f} MB"
    if b > 1024:
        return f"{b / 1024:6.1f} KB"
    return f"{b:6d} B "


def draw_frame(interval):
    tasks = _amiga.list_tasks()
    libs = _amiga.list_libraries()
    ports = _amiga.list_ports()
    mem = _amiga.avail_mem_summary()

    ready = [t for t in tasks if t[2] == "Ready"]
    wait = [t for t in tasks if t[2] == "Wait"]

    print(CLEAR, end="")
    print(f"{BOLD}==== python-amigaos4 sysmon ===={RESET}   "
          f"{DIM}refresh every {interval:.1f}s   (Ctrl-C to quit){RESET}")
    print()

    print(f"{BOLD}Memory:{RESET}")
    print(f"  any     {fmt_bytes(mem['any'])}     "
          f"chip {fmt_bytes(mem['chip'])}     "
          f"fast {fmt_bytes(mem['fast'])}     "
          f"largest {fmt_bytes(mem['largest'])}")
    print()

    print(f"{BOLD}Tasks:{RESET}  {len(tasks)} total   "
          f"{len(ready)} Ready   {len(wait)} Wait")
    top = sorted(tasks, key=lambda x: -x[1])[:8]
    for name, pri, state in top:
        marker = "R" if state == "Ready" else "W"
        print(f"  [{marker}] {pri:>+4}  {name}")
    print()

    print(f"{BOLD}Libraries:{RESET}  {len(libs)} opened   (top 8 by open-count)")
    top_libs = sorted(libs, key=lambda x: -x[3])[:8]
    for name, v, r, oc in top_libs:
        print(f"  v{v:>3}.{r:<3}  opens={oc:<5}  {name}")
    print()

    print(f"{BOLD}Public MsgPorts:{RESET}  {len(ports)}")
    for p in ports[:6]:
        print(f"  {p}")
    if len(ports) > 6:
        print(f"  ... +{len(ports) - 6} more")


def main():
    interval = 2.0
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            pass

    try:
        while True:
            draw_frame(interval)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nsysmon: goodbye.")


if __name__ == "__main__":
    main()
