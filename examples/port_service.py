"""port_service.py — Amiga MsgPort microservice in Python.

Demonstrates the classic Exec IPC paradigm with real workload:

  Worker thread creates a public port "PySvc" and services requests.
  Client thread(s) discover it via FindPort() and issue commands.
  Every command flows over the same MsgPort using PutMsg + WaitPort +
  GetMsg + reply, exactly as a C task-to-task program would.

Backing: amiga.exec's queue.Queue + threading.Event Phase-A simulation.
Wire compatibility with real MsgPorts arrives in Phase C — same source
will run against IExec->CreateMsgPort() etc without changes.

Commands supported by the server:
    ping           → 'pong'
    time           → wallclock ISO string
    sysmem         → dict of free memory bytes (via _amiga.avail_mem_summary)
    tasks          → int count of tasks (via _amiga.list_tasks)
    upper(text)    → text.upper()
    shutdown       → server drains and exits

Run:
    DH1:python-os4 DH1:pytests/examples/port_service.py
"""
import sys, os
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import time
import threading
import amiga.exec as ex

# time.sleep() throws OSError on this OS4 port; use Event.wait as a
# portable replacement.
_sleep_event = threading.Event()
def _sleep(secs):
    _sleep_event.wait(timeout=secs)

try:
    import _amiga
    HAVE_NATIVE = True
except ImportError:
    HAVE_NATIVE = False


# ---------------------------------------------------------------------------
# Server side
# ---------------------------------------------------------------------------

def dispatch(cmd, arg):
    if cmd == "ping":
        return "pong"
    if cmd == "time":
        return time.strftime("%Y-%m-%dT%H:%M:%S")
    if cmd == "sysmem":
        if HAVE_NATIVE:
            return _amiga.avail_mem_summary()
        return {"info": "native _amiga module not built in"}
    if cmd == "tasks":
        if HAVE_NATIVE:
            return len(_amiga.list_tasks())
        return -1
    if cmd == "upper":
        return arg.upper()
    return f"unknown-command:{cmd}"


def server(shutdown_flag):
    port = ex.CreateMsgPort("PySvc", public=True)
    print(f"[server] listening on port 'PySvc' (signal bit={port.signal_bit})")
    handled = 0
    while not shutdown_flag.is_set():
        # Wait up to 0.25s for a wake-up signal so we can honor shutdown.
        m = ex.WaitPort(port, timeout=0.25)
        if m is None:
            continue
        # Drain everything queued right now (Amiga idiom).
        batch = [m]
        while True:
            nxt = ex.GetMsg(port)
            if nxt is None:
                break
            batch.append(nxt)

        for msg in batch:
            cmd = msg.data.get("cmd")
            arg = msg.data.get("arg", "")
            if cmd == "shutdown":
                print("[server] shutdown requested")
                msg.reply(response="bye")
                shutdown_flag.set()
                continue
            handled += 1
            response = dispatch(cmd, arg)
            print(f"[server] {handled:03d}  {cmd}({arg!r}) -> {response!r}")
            msg.reply(response=response)

    ex.DeleteMsgPort(port)
    print(f"[server] done, handled {handled} requests")


# ---------------------------------------------------------------------------
# Client side
# ---------------------------------------------------------------------------

def call(port, cmd, arg="", timeout=2.0):
    """RPC to the service.  Creates a fresh reply port per call for
    simplicity (Amiga programs typically reuse one)."""
    reply_port = ex.CreateMsgPort()
    try:
        ex.PutMsg(port, {"cmd": cmd, "arg": arg}, reply_port=reply_port)
        m = ex.WaitPort(reply_port, timeout=timeout)
        if m is None:
            return None
        return m.data
    finally:
        ex.DeleteMsgPort(reply_port)


def client(name, requests, results):
    # Locate the service by name (Exec FindPort).
    target = None
    for _ in range(20):
        target = ex.FindPort("PySvc")
        if target is not None:
            break
        _sleep(0.05)
    if target is None:
        print(f"[client-{name}] service not found")
        return

    for cmd, arg in requests:
        r = call(target, cmd, arg)
        results.append((cmd, arg, r))
        print(f"[client-{name}] {cmd}({arg!r}) -> {r!r}")


def main():
    shutdown = threading.Event()
    srv = threading.Thread(target=server, args=(shutdown,), daemon=True)
    srv.start()

    results_a, results_b = [], []
    a = threading.Thread(target=client, args=("A", [
        ("ping",  ""),
        ("time",  ""),
        ("upper", "hello world"),
        ("sysmem", ""),
    ], results_a))
    b = threading.Thread(target=client, args=("B", [
        ("tasks", ""),
        ("upper", "amiga rocks"),
        ("ping",  ""),
    ], results_b))
    a.start()
    b.start()
    a.join()
    b.join()

    # Ask the server to shut down cleanly.
    port = ex.FindPort("PySvc")
    if port is not None:
        call(port, "shutdown")

    srv.join(timeout=2.0)

    print()
    print(f"[main] client A got {len(results_a)} responses, "
          f"B got {len(results_b)}.  ✓")


if __name__ == "__main__":
    main()
