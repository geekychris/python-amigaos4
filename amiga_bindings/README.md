# amiga_bindings — the `amiga.*` Python module family for OS4

Roadmap for exposing AmigaOS 4 APIs to Python. This is the value-add
that makes the port worth doing beyond "generic Python on a weird
CPU" — Python scripts that natively drive dos.library, intuition,
graphics, the bridge daemon, and eventually ARexx.

## Phased plan

### Phase A — Pure-Python via bridge (works today after Phase 2)
Wraps the existing `amiga-bridge` client protocol from Python.
The bridge daemon speaks a well-defined line protocol over the
serial + TCP transports. A pure-Python client just needs socket
I/O (Phase 3) to send SCRIPT / SETVAR / CALLHOOK / SCREENSHOT etc.

Scripts get:
- `amiga.bridge.log("info", "Hello from Python")` — emits into the
  bridge log stream, visible to devbench.
- `amiga.bridge.exec("copy A B")` — runs any AmigaDOS command.
- `amiga.bridge.screenshot() -> bytes` — pulls a PNG.
- `amiga.bridge.list_windows()` etc. — inspection helpers.

**Blocked on:** Phase 3 (sockets via bsdsocket.library).

### Phase B — Direct via ctypes
Load `dos.library` / `intuition.library` / `graphics.library`
via ctypes and call their public entry points from Python. This
is the "real" wrapper — no bridge daemon in the loop.

Scripts get:
- `amiga.dos.Execute("cmd", output_file)`
- `amiga.dos.Info() -> [Volume(name, blocks, used)]`
- `amiga.intuition.LockPubScreen("Workbench") -> Screen`
- `amiga.exec.FindTask(name) -> Task`

**Blocked on:** ctypes must work, which needs libffi ported. Newlib
on OS4 has `libffi` in the SDK — probably a Phase 3-4 effort to
enable `_ctypes` in Modules/Setup.local and confirm it links.

### Phase C — Native C extension `_amiga`
Compiled `.so` extension with Python's C API. Fastest, cleanest.
Direct calls to `IExec->FindTask()`, `IDOS->Examine()`,
`IIntuition->OpenWindowTags()`.

**Blocked on:** stable extension-module build path on OS4 (needs
threading + ctypes for the loader machinery). Realistically after
Phases 3-4.

## Module layout (target)

```
amiga/
├── __init__.py          — version + capability probes
├── dos/
│   ├── __init__.py      — Execute, SystemTagList, Info, MakeDir, Delete
│   ├── file.py          — Lock, Examine, ExNext (dir walking)
│   └── path.py          — Amiga path helpers (SplitName, MergePath)
├── exec/
│   ├── __init__.py      — FindTask, Signal, Wait, Alert
│   ├── memory.py        — AvailMem, TypeOfMem
│   └── library.py       — OpenLibrary, CloseLibrary, list opened
├── intuition/
│   ├── __init__.py      — window/screen enumeration + basic control
│   ├── screen.py        — LockPubScreen, ScreenToFront
│   └── window.py        — MoveWindow, SizeWindow, EasyRequest
├── graphics/
│   ├── __init__.py      — RastPort, palette, sprite basics
│   └── copper.py        — copper list reader (Phase C only)
├── arexx/
│   └── __init__.py      — send / listen on ARexx ports
└── bridge/
    ├── __init__.py      — high-level: log/exec/screenshot
    └── client.py        — low-level protocol client (socket transport)
```

## Current status

Nothing here compiles yet. Files below are **specification stubs**
— every function raises `NotImplementedError("phase X")` with the
implementation phase encoded in the message. Tests in
`../tests/amiga/` skip modules that report their phase isn't ready.

This lets the test suite grow now without waiting for Phase 6.
When a phase lands, we implement the corresponding stubs and the
skipped tests start running.
