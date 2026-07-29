"""task_watcher.py — watch for task spawn / exit events on AmigaOS 4.

Polls _amiga.list_tasks() on a timer, diffs against the previous
snapshot, prints one line per spawn / exit.  Runs until Ctrl-C.

This is what a real OS-level monitor looks like from Python:
straight into ExecBase's TaskReady + TaskWait lists via the native
module, no shell-out latency.

Run:
    python3 python3:examples/task_watcher.py [interval]

Try opening / closing programs on the Workbench while it runs and
watch the spawn/exit lines fly by.
"""
import sys, os
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import time

try:
    import _amiga
except ImportError:
    print("task_watcher: needs the _amiga native module (Phase 6).")
    sys.exit(1)


def snapshot():
    """Return a dict {name: (priority, state)} — collapses duplicates
    (rare, but two threads with the same name could share the ExecBase
    node name)."""
    out = {}
    for name, pri, state in _amiga.list_tasks():
        out.setdefault(name, (pri, state))
    return out


def diff(prev, curr):
    spawned = sorted(n for n in curr if n not in prev)
    exited = sorted(n for n in prev if n not in curr)
    changed = []
    for n in curr:
        if n in prev and curr[n] != prev[n]:
            changed.append((n, prev[n], curr[n]))
    return spawned, exited, changed


def main():
    interval = 1.0
    if len(sys.argv) > 1:
        try:
            interval = float(sys.argv[1])
        except ValueError:
            pass

    print(f"[task_watcher] polling every {interval:.1f}s. Ctrl-C to quit.")
    prev = snapshot()
    print(f"[task_watcher] baseline: {len(prev)} tasks")

    try:
        while True:
            time.sleep(interval)
            curr = snapshot()
            spawned, exited, changed = diff(prev, curr)
            now = time.strftime("%H:%M:%S")
            for n in spawned:
                pri, state = curr[n]
                print(f"[{now}] SPAWN  {pri:>+4} {state[:1]}  {n}")
            for n in exited:
                pri, state = prev[n]
                print(f"[{now}] EXIT   {pri:>+4} {state[:1]}  {n}")
            for n, (pri0, s0), (pri1, s1) in changed:
                print(f"[{now}] CHANGE {n}  {pri0}/{s0[:1]} -> {pri1}/{s1[:1]}")
            prev = curr
    except KeyboardInterrupt:
        print("\n[task_watcher] goodbye.")


if __name__ == "__main__":
    main()
