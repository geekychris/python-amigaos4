# python-os4

CPython 3.12.7 port for AmigaOS 4.1 PowerPC (sam460ex / QEMU).

**Status:** Phase 1 complete. Configure works; all core .o files
compile cleanly; POSIX shim layer covers the newlib gaps; gthread stubs cover
libgcc's emutls dependency. Cross-linker produces a **7 MB stripped PowerPC ELF
python.exe binary** ready to deploy to `DH1:python-os4` on the OS4 HDF.

**Runtime verified** under QEMU sam460ex on OS4 4.1 FE with Update 3's
`newlib.library.kmod` (53.87) swapped into `SYS:Kickstart`:

```
1.SYS:> DH1:python-os4 --version
Python 3.12.7
```

The binary is linked against `newlib.library 53.68`; the SDK and Update 3
both ship 53.87 which satisfies it. Base OS4.1 FE ships 53.30 (fails
the version check). Extract Update 3 with `lha x`, push
`Content/Kickstart/newlib.library.kmod` to the OS4 side, `copy` it into
`SYS:Kickstart/newlib.library.kmod CLONE`, reboot.

`print(...)` output doesn't reach stdout yet — that's the Phase 2
workload (frozen stdlib bootstrap so the io + codec subsystem
initialises). `--version` works because it's an early-exit path in
`Modules/main.c` that runs before stdlib init.

## Layout

```
python-os4/
├── Dockerfile           # walkero PPC toolchain + Python 3.12 for build
├── build.sh             # main iteration script (configure / make / clean / shell)
├── setup.local          # Modules/Setup.local — disables ~30 unshimmed stdlib mods
├── amiga_shim.c/h       # POSIX gap-fillers (unsetenv, initgroups, setrlimit...)
├── Python-3.12.7/       # CPython source (unpacked from tarball, patched)
└── build-ppc-amigaos/   # out-of-tree build dir (git-ignored)
```

Only two upstream files patched: `Python-3.12.7/configure` gets ~10 lines of new
cases so `powerpc-unknown-amigaos` is recognised as a cross-compile target. All
other adaptations live in `amiga_shim.h/c` (force-included via `-include` in
CFLAGS) so we don't fork CPython.

## Usage

```bash
docker build -t amiga-python-build:local .   # once (or when Dockerfile changes)
./build.sh configure                          # runs ./configure
./build.sh make                               # configure + make
./build.sh clean                              # nuke build dir
./build.sh shell                              # interactive container
```

## What works (in this snapshot)

- `configure` accepts `--host=powerpc-unknown-amigaos` (2-block patch to
  `configure` — see the `*-*-amigaos*` cases)
- Cross-compile via walkero's `ppc-amigaos-gcc` inside Docker
- `PYTHON_FOR_BUILD` = deadsnakes Python 3.12 (needed by `configure` for
  freeze/regen consistency)
- Hard-float ABI selected (`-mhard-float`) matching newlib's libc
- `SSIZE_MAX` defined via CFLAGS
- ~73 core interpreter `.o` files build cleanly (Object system, ceval,
  parser, compile, import, marshal, unicode, symtab, tracemalloc, GIL...)
- `Modules/Setup.local` overrides after configure to skip ~30 modules with
  hard POSIX deps we haven't shimmed
- POSIX shim layer wired via `-include /work/amiga_shim.h`:
  - `unsetenv()`, `initgroups()`, `setrlimit()`, `getrlimit()` — real stubs
  - `fileno()`, `fdopen()`, `popen()`, `pclose()` — prototypes only (newlib
    has the code but doesn't expose the decls in default feature-test mode)
  - `O_NOFOLLOW`, `O_CLOEXEC`, `O_DIRECTORY` — defined as 0

## Phase 2 (next): stdlib bootstrap

`--version` runs; `print(x)` returns silently. To get any real Python
behaviour we need CPython's frozen stdlib installed alongside the
interpreter so `import sys, os, encodings, io, codecs` work at startup.

Concrete Phase-2 workload:

- Freeze the pure-Python stdlib and install `Lib/python3.12/` into an
  Amiga-side directory (probably `DH1:python-os4-lib/`)
- Point `sys.path` at that dir via `PYTHONHOME` / `PYTHONPATH` env or
  a `python.exe`-side config file
- Re-enable the C modules we currently disable in `setup.local` that
  don't actually need forks/sockets/threads (`_json`, `_csv`,
  `unicodedata`, `_hashlib` — some of these might slot in trivially)
- Verify `import sys; print(sys.version)` produces output

That unblocks Phase 3 (sockets via bsdsocket) → Phase 4 (threading +
subprocess) → Phase 5 (pip) → Phase 6 (native `_amiga` bindings).

## Development inner loop

1. `./build.sh make`
2. Read `/tmp/py-build.log` or scroll output for first `error:` /
   `undeclared` / `implicit declaration of function`
3. If a POSIX function is missing → add stub to `amiga_shim.c/h`
4. If a POSIX constant is missing → `#define` it in `amiga_shim.h`
5. If a whole module can't be shimmed → add its name to `setup.local`
6. If a core CPython file has an Amiga-hostile call — future work: create
   `Python-3.12.7/Amiga/` platform dir with proper `pyconfig.h` overrides
   (patterned after `PC/` for Windows)
7. `./build.sh make` again — usually fixes 1-2 issues at a time

## Phased roadmap (recap of the up-front assessment)

- **Phase 1** — Bootstrap. Get `python3 -c "print(1)"` running. ~3-5 weeks.
- **Phase 2** — Stdlib freeze + install. ~3-5 weeks.
- **Phase 3** — Sockets + SSL via bsdsocket.library + AmiSSL. ~2-3 weeks.
- **Phase 4** — Threading + subprocess (pthread shim, SystemTagList). ~4-6 weeks.
- **Phase 5** — pip install. ~2-3 weeks.
- **Phase 6** — `_amiga` bindings (Intuition, DOS, bridge client). ongoing.

Half-time single-engineer estimate: 4-6 months to "usable for scripts",
8-12 months to "pip-installs-things-and-they-mostly-work".
