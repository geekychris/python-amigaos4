# python-amigaos4

**CPython 3.12.7 port for AmigaOS 4.1 PowerPC** — cross-compiled from
Linux/macOS via Docker (walkero/amigagccondocker), targeted at
sam460ex on QEMU (also runs on real hardware once you get the newlib
libraries right).

Status: **all six roadmap phases done + real Intuition windows +
turtle-graphics compat layer running unmodified freegames snake**.

```
DH1:> python-os4 --version
Python 3.12.7

DH1:> python-os4 pytests/examples/snake.py     # ← real Intuition window
```

## What works

| capability                       | how                                                       |
| -------------------------------- | --------------------------------------------------------- |
| Pure Python 3.12.7               | 298/298 language + stdlib checks pass on real OS4         |
| Sockets (TCP client + listen)    | `_socket` static builtin over bsdsocket.library           |
| Threads (Lock/RLock/Sem/Event/TPE)| `_thread` + threading + concurrent.futures                |
| zlib decompression               | `zlib` static builtin                                     |
| pip 24.2 (import + install pure-Py wheels) | bundled + `amiga.pip` shim (subprocess-free)              |
| **SQLite 3.34.0**                | `_sqlite3` static builtin over SDK's libsqlite3.a         |
| **Real Intuition windows**       | `_amiga.open_window` / `draw_text` / `wait_message`       |
| **Turtle graphics compat**       | `amiga.turtle` on top of `_amiga` — runs `freegames.snake`|
| Native exec/dos introspection    | `_amiga.list_tasks` / `list_libraries` / `avail_mem_summary` |

Not yet: SSL (blocked on AmiSSL header wiring), real fork/exec
(architectural — use `amiga.os.run()` shim), interactive `python -m
pip install` (subprocess boundary — use `amiga.pip.install_wheel`).

## Repository layout

```
python-amigaos4/
├── build.sh                  # top-level cross-compile driver (docker)
├── scripts/
│   ├── build.sh              # thin wrapper + --strip pass
│   └── deploy.sh             # generates the MCP commands to push everything
├── setup.local               # Modules/Setup overrides — pins C extensions static
├── Modules-*.patch           # small CPython patches for OS4 quirks
├── Lib-*.patch, Python-*.patch, Objects-*.patch
├── amiga_shim.c/h            # POSIX gap-fillers (nanosleep, ioctl, fcntl, ...)
├── _amigamodule.c            # native _amiga extension (22 entry points)
├── amiga_bindings/
│   └── amiga/                # Python-side wrappers built on _amiga
│       ├── dos/              # amiga.dos: Info, Assign, Execute, walk, ...
│       ├── exec/             # amiga.exec: MsgPort, Signal, Wait, list_tasks
│       ├── intuition/        # amiga.intuition: Window/IDCMP paradigm + EasyRequest
│       ├── bridge/           # amiga.bridge: TCP client for the amiga-bridge daemon
│       ├── os/               # amiga.os.run — subprocess-drop-in for OS4
│       ├── pip/              # amiga.pip — subprocess-free wheel installer
│       └── turtle/           # amiga.turtle — freegames-compatible shim
├── examples/                 # 10 demo apps + snake game (see docs/DEMOS.md)
├── tests/                    # 15 test files (language/stdlib/io/amiga)
└── docs/
    ├── DEMOS.md              # screenshot gallery + Mac↔Amiga snake comparison
    └── RUNNING.md            # setup, PYTHONHOME/PATH, tracer usage, cleanup
```

## Build

Prereq: Docker Desktop.  One-time image build (~500 MB pull):

```
docker pull walkero/amigagccondocker:os4-gcc11-arm64   # or amd64
docker build -t amiga-python-build:local .              # our thin wrapper
```

Then:

```
scripts/build.sh --strip
```

Produces `build-ppc-amigaos/python-stripped.exe` (≈ 9 MB PowerPC ELF,
52 built-in C extensions, dynamically links `newlib.library 53.87`).

Full command reference: `scripts/build.sh -h`.

## Deploy to OS4

Assumes AmigaOS 4.1 FE booted (QEMU sam460ex or real hardware) with
the `amiga-bridge` daemon running.  See
[amiga_mcp](https://github.com/geekychris/amiga_mcp) for the
emulator+bridge stack.

```
scripts/deploy.sh
```

Prints the exact `amiga_push_file` / `amiga_transfer` calls to paste
into a Claude Code session (or any MCP client wired to the
amiga-devbench server).  Options:

* `--binary-only` — just push `python-os4`
* `--code-only`   — bindings + examples + tests, skip binary
* `--stdlib`      — also stage the pure-Python stdlib flat files
                    (one-time per new OS4 image)

## Running

**CRITICAL first-time-per-boot setup** — Python's built-in getpath
doesn't autodiscover `DH1:lib` on our OS4 build, and the init failure
is silent:

```
setenv PYTHONHOME DH1:
setenv PYTHONPATH DH1:lib
```

Then:

```
DH1:python-os4 RAM:tiny.py
DH1:python-os4 DH1:pytests/examples/clock.py           # windowed
DH1:python-os4 DH1:pytests/examples/snake.py           # turtle game
```

Full details, tracer usage for future silent-init bugs, and RAM:
tempfile housekeeping: **[docs/RUNNING.md](docs/RUNNING.md)**.

## Demos + screenshots

**[docs/DEMOS.md](docs/DEMOS.md)** — every windowed app, live
screenshots from a QEMU session, and a side-by-side comparison of
`freegames.snake` on macOS (stdlib turtle) vs. AmigaOS 4 (via our
`amiga.turtle` shim).

Highlights (all real Intuition windows):

| app              | what it does                                        |
| ---------------- | --------------------------------------------------- |
| `planner.py`     | **full calendar + notes app** with SQLite storage, tag search, event fields (title/date/time/attendees/notes/url/tags) |
| `clock.py`       | wallclock + uptime, redrawn every second            |
| `window_sysmon.py` | live memory/tasks/libraries dashboard             |
| `hello_ipc.py`   | Amiga MsgPort microservice — worker + 2 clients     |
| `port_service.py`| full RPC over MsgPort (ping/time/upper/shutdown)    |
| `snake.py`       | grantjenks/free-python-games snake, ported          |
| `snake_verifiable.py` | + audit log to `T:snake_log.txt` for testing   |
| `gui_form.py`    | multi-step Intuition RequestChoice popups           |
| `sysmon.py`      | ANSI TUI system monitor                             |
| `task_watcher.py`| spawn/exit event log via `_amiga.list_tasks` diff   |

## The port's shape

### `_amiga` — native C module (static builtin)

Direct calls into IExec / IDOS / IIntuition / IGraphics.  22 entry
points across:

* **exec**: `find_task`, `avail_mem`, `avail_mem_summary`,
  `list_tasks`, `list_libraries`, `list_ports`
* **dos**: `current_dir_name`, `volume_info`
* **intuition**: `open_window`, `close_window`, `window_geom`,
  `clear_window`, `draw_text`, `get_message`, `wait_message`,
  `active_window`
* **graphics**: `draw_line`, `fill_rect`, `dot`, `obtain_pen`,
  `release_pen`

Plus 12 IDCMP\_\*, 7 WFLG\_\*, 6 MEMF\_\* constants exposed.

Interface pointers (`IIntuition`, `IGraphics`) opened via
`OpenLibrary` + `GetInterface` at module import (`-lauto` position
in the link line puts the auto-openers too early to be pulled in).

### `amiga.*` — Python-level wrappers

Pure Python, sit on top of `_amiga` (native) or `os` (POSIX) or
shell-out via `os.system`.  Model classic Amiga paradigms:

* `amiga.exec.MsgPort / PutMsg / WaitPort / GetMsg / ReplyMsg /
  FindPort / AllocSignal / Wait / Signal` — the message-passing
  idiom, backed by `queue.Queue` + `threading.Event` today, wires
  to real IExec calls in Phase C.
* `amiga.intuition.OpenWindow / draw_text / wait_message / events`
  — full IDCMP-drain event loop.  In sim mode logs to console;
  with `_amiga` available it opens real Intuition windows on
  Workbench.
* `amiga.turtle` — subset of stdlib `turtle` sufficient to run
  grantjenks/free-python-games (snake, paint, pong, tron, ...).
  Colour names → `ObtainBestPen`, coordinate translation
  turtle-origin-centre → Intuition-top-left.

### Build tuning

* `setup.local` promotes ~19 C extensions from `*shared*` to
  `*static*` because our loader has no dlopen equivalent.  Currently:
  math, cmath, _datetime, _json, _random, _pickle, _heapq, _bisect,
  _struct, _csv, _contextvars, _queue, _statistics, _opcode,
  _zoneinfo, array, select, binascii, unicodedata, _socket, zlib,
  _amiga.
* `amiga_shim.c/h` fills newlib gaps: `nanosleep` (via `Delay`),
  `getrandom` (weak LCG), `ioctl` (no-op), `fcntl` (no-op),
  `unsetenv`, `initgroups`, `setrlimit`/`getrlimit`, gthread stubs,
  `INET_ADDRSTRLEN`.  Force-included via `-include amiga_shim.h`.

## Related

* [amiga_mcp](https://github.com/geekychris/amiga_mcp) — the
  cross-development environment: QEMU wrapper, `amiga-bridge`
  daemon, `amiga-devbench` MCP server that Claude Code drives to
  push files, run commands, capture screenshots, inject keys.

## License

MIT (see `LICENSE`).  CPython source under Python's own PSF license.
