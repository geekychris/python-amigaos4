# python-amigaos4 examples

Scripts that show off what Python 3.12 on AmigaOS 4.1 PPC can do
right now (Phase A) — and the shape of things to come (Phase B/C).

| example | works today | demonstrates |
| ------- | ----------- | ------------ |
| `hello_dos.py`  | **yes** — everything real | filesystem introspection through `amiga.dos`: Info, Assign, walk, Examine, Execute |
| `hello_ipc.py`  | **yes** — full simulation | classic Exec message-passing paradigm: CreateMsgPort / PutMsg / WaitPort / GetMsg / ReplyMsg / FindPort |
| `hello_gui.py`  | mixed — EasyRequest real, window simulated | Intuition IDCMP event loop shape; EasyRequest via `RequestChoice` pops a real requester today |

## Running

Deploy examples/ to the target (same tree pattern as tests/):
```
amiga_transfer  examples/  DH1:pytests/examples/
```

Then on the Amiga:
```
DH1:python-os4 DH1:pytests/examples/hello_dos.py
DH1:python-os4 DH1:pytests/examples/hello_ipc.py
DH1:python-os4 DH1:pytests/examples/hello_gui.py
```

## The paradigm the bindings model

Amiga programming is **message-driven**: you get a MsgPort, you Wait on it,
you drain incoming Messages, you Reply.  Every subsystem hands you a port —
Intuition sends IDCMP events, dos.library sends packet replies, timer.device
sends TimeRequests back, custom services register public ports for their
clients to find.

`amiga.exec.MsgPort` / `CreateMsgPort` / `PutMsg` / `WaitPort` / `GetMsg` /
`ReplyMsg` / `FindPort` model this exactly.  In Phase A they're backed by
`queue.Queue` + `threading.Event` so scripts learn (and can unit-test)
the pattern on today's port.  When Phase C wires in a native `_amiga`
module, the same source binds onto real `IExec->CreateMsgPort()`.

The paradigm is worth learning even if you're only running in simulation
today — it's how you'll write real Amiga UIs, real ARexx handlers, real
device drivers.  Cargo-culting a `while True: time.sleep(0.1)` loop and
polling flags is the wrong shape for this OS.
