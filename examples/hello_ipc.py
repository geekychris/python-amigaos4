"""hello_ipc — Amiga message-passing paradigm from Python.

Demonstrates the classic Exec IPC pattern using amiga.exec's Phase A
implementation (queue.Queue + threading.Event under the hood, but the
API surface matches real exec.library so scripts port cleanly to
Phase B/C):

    port = CreateMsgPort("MyService", public=True)
    while running:
        WaitPort(port)                  # blocks until a message arrives
        while (m := GetMsg(port)):      # drain everything queued
            process(m.data)
            ReplyMsg(m, response)

Runs today on the OS4 Python port; will run unchanged when the exec
bindings flip from queue-simulation to real IExec calls.
"""
import sys, os
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import time
import threading

import amiga.exec as ex


def worker(shutdown):
    """A tiny 'service' task listening on a public port."""
    port = ex.CreateMsgPort("EchoService", public=True)
    print(f"[worker] listening, signal bit={port.signal_bit}")
    while not shutdown.is_set():
        m = ex.WaitPort(port, timeout=0.2)
        if m is None:
            continue
        # Drain: WaitPort returned the first one; GetMsg pulls the rest.
        msgs = [m]
        while True:
            nxt = ex.GetMsg(port)
            if nxt is None:
                break
            msgs.append(nxt)
        for msg in msgs:
            print(f"[worker] got {msg.data!r}")
            msg.reply(response=f"echo:{msg.data}")
    ex.DeleteMsgPort(port)
    print("[worker] done")


def client():
    """Look up the public port + send messages + wait for replies."""
    reply_port = ex.CreateMsgPort("ClientReply")

    # Discover the service by name — classic Amiga FindPort dance.
    target = None
    for _ in range(20):
        target = ex.FindPort("EchoService")
        if target is not None:
            break
        time.sleep(0.05)
    if target is None:
        print("[client] service never showed up")
        return

    for word in ["hello", "amiga", "os4"]:
        print(f"[client] sending {word!r}")
        ex.PutMsg(target, word, reply_port=reply_port)
        reply = ex.WaitPort(reply_port, timeout=2)
        if reply is None:
            print("[client] no reply (timeout)")
        else:
            print(f"[client] got reply: {reply.data!r}")

    ex.DeleteMsgPort(reply_port)


if __name__ == "__main__":
    shutdown = threading.Event()
    t = threading.Thread(target=worker, args=(shutdown,), daemon=True)
    t.start()
    try:
        client()
    finally:
        shutdown.set()
        t.join(timeout=1)
    print("\nhello_ipc: OK")
