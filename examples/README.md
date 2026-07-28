# python-amigaos4 examples

Scripts that show off what Python 3.12 on AmigaOS 4.1 PPC can do right now
across phases 1-6.

| example                 | what it demos                                         | uses                              |
| ----------------------- | ----------------------------------------------------- | --------------------------------- |
| `hello_dos.py`          | filesystem introspection                              | amiga.dos (Phase A)               |
| `hello_ipc.py`          | MsgPort/PutMsg/WaitPort/GetMsg round-trip             | amiga.exec (Phase A)              |
| `hello_gui.py`          | IDCMP event loop shape                                | amiga.intuition (Phase A sim)     |
| **`sysmon.py`**         | live TUI system monitor — mem / tasks / libs / ports  | `_amiga` native (Phase 6)         |
| **`port_service.py`**   | Amiga MsgPort microservice (worker + clients)         | amiga.exec + `_amiga`             |
| **`gui_form.py`**       | REAL Intuition requesters (RequestChoice)             | amiga.intuition + `_amiga`        |
| **`task_watcher.py`**   | live spawn / exit tracker via ExecBase walks          | `_amiga.list_tasks`               |

Bold entries are the "real" demos — everything uses the native `_amiga`
module and prints against actual OS4 state (73 tasks, 86 libraries,
1 GB free RAM on the sam460ex QEMU target).

## Running

Deploy once:
```
amiga_transfer  examples/  python3:examples/
```

Then on the Amiga (or via `amiga_dos_command`):
```
python3 python3:examples/hello_dos.py
python3 python3:examples/hello_ipc.py
python3 python3:examples/hello_gui.py

python3 python3:examples/sysmon.py               # Ctrl-C to quit
python3 python3:examples/sysmon.py 0.5           # 500ms refresh

python3 python3:examples/port_service.py         # full round-trip
python3 python3:examples/task_watcher.py         # long-running
python3 python3:examples/gui_form.py             # pops real windows!
```

## The paradigm we're modelling

Amiga programming is **message-driven**: get a MsgPort, Wait on it, drain
Messages, Reply.  Every subsystem hands you a port — Intuition sends
IDCMP events, dos.library sends packet replies, timer.device sends
TimeRequests back, custom services register public ports for clients
to find.

`amiga.exec.MsgPort` / `CreateMsgPort` / `PutMsg` / `WaitPort` / `GetMsg` /
`ReplyMsg` / `FindPort` model this exactly.  In Phase A they're backed by
`queue.Queue` + `threading.Event` so scripts learn (and can unit-test) the
pattern on today's port.  When Phase C wires in real IExec calls, the
same source binds onto real `IExec->CreateMsgPort()`.

The paradigm is worth learning even in simulation today — it's how you'll
write real Amiga UIs, real ARexx handlers, real device drivers.
Cargo-culting a `while True: time.sleep(0.1)` loop and polling flags is
the wrong shape for this OS.
