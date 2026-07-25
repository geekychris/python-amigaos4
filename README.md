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

`print(...)` output doesn't reach stdout yet — early exit paths
(`-V`, `-h`, `--version`) print via `fprintf(stdout,...)` before
`Py_Initialize()` runs, and those work perfectly. Anything past
Python init (running `-c` code, importing modules, syntax errors)
returns silently even with `-v`, `-X dev`, `PYTHONVERBOSE=1`. That's
Phase 2's core bug: stdout is being disconnected somewhere between
`Py_Initialize()` calling `_Py_InitializeMain()` and the runtime
actually writing to fd 1.

Not tractable to fix by tweaking shims blind. Needs a debug interp
build + qemu GDB attach so we can single-step through the initconfig
+ pylifecycle paths and see where the FD gets dropped. Likely
suspects: `_Py_open_cloexec_works` sentinel, `Py_INITIALIZE_TERMINATED`
early-exit paths, or newlib's `fdopen()` shim (declared but its
runtime behaviour on OS4 not verified).

Stdlib packaging works — `python312.zip` (1.9 MB, 372 modules)
sits at `DH1:python312.zip`, `PYTHONHOME=DH1:` and
`PYTHONPATH=DH1:python312.zip` are set. Verified via `getenv`.
The zip itself is fine (verified round-trip with host Python).

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

## Phase 2 status: silent init failure

Stdlib is packaged + installed:
- `python312.zip` (1.9 MB, 372 pure-Python modules from `Lib/`) at
  `DH1:python312.zip`
- `PYTHONHOME=DH1:`, `PYTHONPATH=DH1:python312.zip` set in ENV:
- OS4 side sees them fine: `getenv PYTHONPATH` returns the path

But `DH1:python-os4 -c "1"` returns exit 0 with **zero output**,
even with `-v`, `-X dev`, `PYTHONVERBOSE=1`. Same for `-c "1/0"`
(should traceback) and `-c "syntax error!"` (should SyntaxError).
`-V` and `-h` work perfectly because they're early-exit paths.

Something in `Py_Initialize()` disconnects stdout/stderr before the
Python-visible I/O system takes over. Next step is a debug build
plus a GDB attach via QEMU's stub (`start-qemu-os4.sh --gdb`) to
walk through `_Py_InitializeMain()` and find where fd 1 gets
dropped. Suspects on the list:
- newlib `fdopen()` shim — I declared the prototype but never
  verified the underlying newlib implementation on OS4
- `_Py_open_cloexec_works` interaction with our `O_CLOEXEC=0`
- Some clib2/newlib divergence in how sys.stdout gets its underlying FILE*

Not "1 more shim to add" — needs interactive symbolic debugging.
When that's cracked, `print()` will start working and the rest of
Phase 2 (module discovery through the zip) will fall out because
the stdlib packaging is already correct.

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

## Silent-init diagnostic notes (checked in for handoff)

### Established facts

- `-V` / `-h` / `--version` produce their fprintf output normally.
- Any codepath that goes through `Py_Initialize` (`-c code`, script file
  execution, even `-c "1/0"` or `-c "syntax error!"`) exits with **no output
  written anywhere** — verified by redirecting to `RAM:sout`, file exists but
  is empty.
- `os.write(1, b"raw\n")` in a Python script is also silent.
- A Python script that does `os.open("RAM:marker", O_WRONLY|O_CREAT)` does NOT
  create the marker file — so Python isn't even reaching the script body.
- A hello.c compiled with the *exact same* toolchain flags
  (`-mcrt=newlib -mhard-float -mcpu=440`) prints stdout+stderr normally.
- No Grim Reaper dialog appears; `amiga_last_crash` returns "no crash data".
- `why` in the OS4 shell after python-os4 exits says "The last command
  did not set a return code" — so the return-code propagation from newlib
  exit() to AmigaDOS shell is also broken (separate issue).

### Diagnosis in progress

Added file-based probes to `pymain_main` in `Modules/main.c` that write
stage markers to `RAM:pymain.log`:

- `A: enter pymain_main` — proves `main() → pymain_main` runs
- `B: after pymain_init exitcode=? exception=?` — proves `Py_Initialize`
  returned (with what status)
- `C: about to Py_RunMain`
- `D: Py_RunMain returned N`

The next session's first action should be:
1. Deploy the probe-instrumented binary (it built cleanly here but the bridge
   transfer failed mid-way — QEMU restart needed).
2. Run any `-c ...` and check `type RAM:pymain.log`.
3. Whichever letter is the last one seen pinpoints the silent-death region.
4. Add finer-grained probes to bisect.

### Working hypothesis

Most likely: `Py_Initialize` completes (status.exitcode = 0, exception = 0),
`init_sys_streams` binds `sys.stdout` to fd 1 via `create_stdio`, but
`_io_FileIO_write_impl` on OS4 doesn't reach the underlying `write(fd, ...)`.
Suspect newlib's clib-side FILE* → BPTR translation for fds 1/2 that we
inherited from the shell process, vs. how Python opens its `_io.FileIO`
BufferedWriter. Might be a `fdopen` issue (our shim declares the prototype
but the underlying newlib impl on OS4 may not support duping fd 1).

Alternative: `Py_Initialize` FAILS silently (some `_PyStatus_ERR` return that
gets swallowed because `pymain_exit_error` uses `Py_ExitStatusException`
which writes to `stderr` — which on our build might be closed / redirected
to void).
