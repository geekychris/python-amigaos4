# python-amigaos4

**CPython 3.12.7 for AmigaOS 4.1 PowerPC.**

Cross-compiled from Linux/macOS via Docker (walkero/amigagccondocker),
targeted at the QEMU sam460ex machine and real hardware. Runs modern
Python — including third-party pure-Python wheels — on top of newlib
+ bsdsocket + Intuition. Ships with a native `_amiga` extension for
direct calls into Exec / DOS / Intuition / Graphics and a small
`amiga.*` package family that wraps the classic OS4 paradigms in
idiomatic Python.

## Why

There's no maintained CPython for AmigaOS 4 in the wild. The port
exists so people can write scripts, run existing pure-Python
libraries, prototype Amiga apps in a high-level language, and reach
Intuition / DOS / Exec without having to write C. It's a real
interpreter, not a subset — `pip install`, `import sqlite3`, `import
threading`, `import ssl` all work.

## Capabilities

| capability | how |
| ---------- | --- |
| Pure Python 3.12.7 (all language + most stdlib) | 298 checks pass on OS4 |
| TCP sockets (client + listen) | `_socket` static builtin over bsdsocket.library |
| Threads (Lock/RLock/Sem/Event/ThreadPoolExecutor) | `_thread` + threading + concurrent.futures |
| SQLite 3.34.0 | `_sqlite3` static builtin over the SDK's libsqlite3.a |
| zlib decompression | `zlib` static builtin |
| pip 24.2 (bundled) — install pure-Python wheels | `amiga.pip.install_wheel()` |
| `import ssl` / `import hashlib` (optional) | statically linked against AmiSSL, opens `amissl.library` **lazily** on first import |
| HTTPS GET end-to-end | `amiga.https.get(url)` shell-out through `openssl s_client` (works around a fd-interop bug between `_ssl` and `_socket`) |
| Real Intuition windows | `_amiga.open_window` / `draw_text` / `wait_message` |
| Turtle graphics compat | `amiga.turtle` on top of `_amiga` — runs unmodified freegames snake/paint |
| Exec / DOS / MsgPort introspection | `_amiga.list_tasks` / `list_libraries` / `list_ports` / `avail_mem_summary` |
| ARexx send + reply | `_amiga.rexx_send` / `amiga.arexx` |

**AmiSSL is optional**: the interpreter is linked so that
`amissl.library` opens on first `import ssl` (not at process start).
Users who don't need SSL don't have to install AmiSSL at all;
`python -V`, `import json`, `import sqlite3` all work on a stock OS4.

## Build

Requires Docker Desktop.

```bash
# One-time — pulls the walkero cross-compile toolchain (~500 MB)
# then builds our thin wrapper image.
docker pull walkero/amigagccondocker:os4-gcc11-arm64   # or -amd64
docker build -t amiga-python-build:local .

# Build. Output: build-ppc-amigaos/python.exe (unstripped, ~56 MB)
./build.sh make
```

Strip for deployment:

```bash
docker run --rm -v "$(pwd):/work" amiga-python-build:local \
  ppc-amigaos-strip -sR.comment /work/build-ppc-amigaos/python.exe \
                                -o /work/build-ppc-amigaos/python-stripped
# → ~15 MB, all 52 built-in C extensions included
```

## Install on OS4

Prerequisites on the target:

```
python3         # the interpreter (rename python-stripped to this)
DH1:lib/               # the Python stdlib — see Deploy below
```

Optional (only if you want HTTPS):

```
LIBS:amisslmaster.library    # AmiSSL runtime, from
LIBS:AmiSSL/amissl_v3xx.library    # https://github.com/jens-maus/amissl
DH1:AmiSSL/Certs/                  # CA cert bundle from same
DH1:openssl                        # OpenSSL CLI from same
```

The `scripts/install_amissl_on_os4.py` installer automates all four
(downloads latest release, uploads via devbench, deploys). See
[docs/INSTALL.md](docs/INSTALL.md).

Set the Python search path **once per boot** (or add to
`S:User-Startup` — the installer does this for AmiSSL):

```
; setenv PYTHONHOME python3:
; setenv PYTHONPATH python3:lib
```

Without those, Python can't find `encodings` and dies silently
during `init_fs_encoding`. See [docs/RUNNING.md](docs/RUNNING.md)
for the full recipe, tracer logs for debugging startup failures,
and how to persist the env vars across reboots.

### Deploying via amiga_mcp

The [amiga_mcp](https://github.com/geekychris/amiga_mcp) repo
provides a QEMU wrapper, an `amiga-bridge` daemon, and an MCP server
that speaks a small protocol for file transfer + command execution
against a running OS4 target. `scripts/deploy.sh` prints the exact
transfer commands to paste into a Claude Code / MCP session:

```bash
./scripts/deploy.sh                # everything (binary + bindings + examples + tests)
./scripts/deploy.sh --binary-only  # just the python-os4 executable
./scripts/deploy.sh --code-only    # bindings + examples + tests, skip binary
./scripts/deploy.sh --stdlib       # also stage lib/ (one-time per new OS4 image)
```

## Running

Sanity check:

```
python3 -V
Python 3.12.7
```

Run a script:

```
python3 RAM:tiny.py
python3 python3:examples/hello_dos.py
```

Run a windowed app:

```
python3 python3:examples/clock.py       # wall clock in an Intuition window
python3 python3:examples/planner.py     # calendar + SQLite notes
python3 python3:examples/snake.py       # freegames snake via amiga.turtle
```

The interactive menu picker exposes every example without needing
to remember paths:

```
execute DH1:scripts/menu
```

(Scripts in `DH1:scripts/` are AmigaDOS launcher files that set
PYTHONHOME/PYTHONPATH then run the matching `.py`. See
`scripts/launchers/` in this repo for the sources.)

## Examples

`examples/` — end-to-end demos of what the port can do.

| example | what it demonstrates |
| ------- | -------------------- |
| `hello_dos.py` | filesystem walk via `amiga.dos` |
| `hello_ipc.py` | MsgPort microservice (worker + 2 clients) |
| `hello_gui.py` | IDCMP event-loop shape (sim mode) |
| `gui_form.py` | real Intuition `RequestChoice` / `RequestString` dialogs |
| `sysmon.py` | live ANSI TUI: memory / tasks / libs / ports |
| `window_sysmon.py` | same, but in an Intuition window |
| `clock.py` | wallclock + uptime, redrawn every second |
| `port_service.py` | RPC over MsgPort (ping / time / upper / shutdown) |
| `task_watcher.py` | live spawn/exit tracker via ExecBase walks |
| `planner.py` | full calendar + notes app with SQLite storage |
| `snake.py` | grantjenks/free-python-games snake, unmodified |
| `snake_verifiable.py` | + audit log for automated verification |
| `arexx_demo.py` | send ARexx commands to running apps |
| `rexx_console.py` | interactive ARexx REPL |
| `browser.py` | text-mode web browser — HTTP via urllib, HTTPS via `amiga.https` |
| `web_notes.py` | tiny web server (raw sockets) with notes CRUD |
| `taskkill.py` | list + kill tasks by name/pattern |
| `fileman.py` | dual-pane file manager |
| `pydiags.py` | subcommand-driven diagnostic tool (env / dns / http / ssl / ...) |
| `menu.py` | interactive picker for everything above |

**Detailed docs + screenshots:** [docs/DEMOS.md](docs/DEMOS.md).

## Tests

`tests/` — a small custom runner that produces one-line
`PASS:` / `FAIL:` / `SKIP:` results per file.

Categories:
- `language/` — arithmetic, strings, control flow, classes, iterators, exceptions
- `stdlib/` — math, json, re, collections, itertools, functools, datetime
- `io/` — file I/O against `RAM:`
- `amiga/` — probes `amiga_bindings/` (bridge, dos, exec, intuition)

Run one:

```
python3 python3:language/test_control_flow.py
```

Run all (from `amiga_mcp` with a live bridge):

```
for t in python3:language/#? python3:stdlib/#? python3:io/#?
  python3 $t
```

Full explanation of the runner + how to add tests:
[tests/README.md](tests/README.md).

### Health-check tool

`pydiags` is a self-contained probe of the runtime — useful both
for users diagnosing setup and for CI regression checks:

```
python3 python3:examples/pydiags.py env      # what Python thinks it sees
python3 python3:examples/pydiags.py socket 8.8.8.8 53
python3 python3:examples/pydiags.py dns example.com
python3 python3:examples/pydiags.py http http://example.com/
python3 python3:examples/pydiags.py ssl      # 6-step SSL/HTTPS probe
python3 python3:examples/pydiags.py tasks    # Amiga tasks + libs
```

Interactive TUI mode (menu-driven) when run without args.

## Layout

```
python-amigaos4/
├── build.sh                    # top-level cross-compile driver (docker)
├── setup.local                 # Modules/Setup overrides — pins C extensions static
├── Modules-*.patch             # small CPython patches for OS4 quirks
├── amiga_shim.c/h              # POSIX gap-fillers (nanosleep, ioctl, ...)
├── amissl_lazy.c               # lazy amissl-library opener (replaces libamisslauto)
├── _amigamodule.c              # native _amiga extension (~25 entry points)
├── amiga_bindings/amiga/       # Python-side wrappers on top of _amiga
│   ├── dos/       exec/        intuition/    graphics/
│   ├── bridge/    os/          pip/          turtle/
│   ├── https/     netfix/      arexx/        ui/
├── examples/                   # demo apps (see table above)
├── tests/                      # language / stdlib / io / amiga
├── scripts/                    # build.sh, deploy.sh, install_amissl_on_os4.py, launchers/
└── docs/                       # INSTALL / RUNNING / DEMOS
```

## Future work

Not yet solved:

- **Full HTTPS via `_ssl`** — Python's `_socket` module opens
  bsdsocket handles that AmiSSL's SSL layer can't reach across; the
  handshake returns `EBADF`. Workaround for now is `amiga.https`
  shell-out to the openssl CLI. Real fix is either patching `_ssl.c`
  to route through AmiSSL's own socket base, or bridging via
  `ObtainSocket`.
- **`fork` / `exec`** — architecturally at odds with AmigaOS process
  model. Users needing subprocess-style workflows should use
  `amiga.os.run()` (shell-out via `System()`) or `amiga.exec.MsgPort`
  for local IPC.
- **Interactive `python -m pip install`** — subprocess boundary
  crosses into the `fork` gap above. Programmatic path via
  `amiga.pip.install_wheel(path)` works today.
- **Native `ctypes` / `_decimal` / `pyexpat`** — currently
  `*disabled*`. Blocked on either the walkero SDK layout
  (no libffi headers in scope) or on newlib API gaps.
- **Rebuild with `--prefix=/DH1`** so `PYTHONHOME`/`PYTHONPATH` no
  longer have to be set by hand at every boot.
- **`_ssl` bsdsocket integration** — the underlying task #94 fix that
  would let `urllib.request` do HTTPS natively without the shell-out.

## Related

- [amiga_mcp](https://github.com/geekychris/amiga_mcp) — the
  cross-development environment used by everything in this repo:
  QEMU sam460ex wrapper, `amiga-bridge` daemon (runs on OS4, speaks
  a small protocol over TCP), `amiga-devbench` MCP server (host-side,
  drives file transfer / command execution / screenshots / key
  injection from Claude Code or any MCP client). Also hosts the
  `tools/https_get/` reference C tool and the AmiSSL installer.

## License

MIT (see `LICENSE`). CPython source is under Python's PSF license.
AmiSSL runtime is Apache-2.0 (Hyperion / AmiSSL Open Source Team).
