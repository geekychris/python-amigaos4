# Installing Python on AmigaOS 4

End-to-end setup from zero (fresh dev-machine, fresh OS4 image).

## 1. Prerequisites on the dev machine (macOS / Linux)

**Docker Desktop** (or engine).  ~500 MB will be pulled for the
cross-compile image.

Optional (much nicer workflow):

* [amiga_mcp](https://github.com/geekychris/amiga_mcp) — the QEMU
  wrapper, `amiga-bridge` daemon, and `amiga-devbench` MCP server.
  Every deploy/test in this doc that shows an `amiga_*` tool call
  is invoked through devbench from a Claude Code session.

If you don't want the MCP stack, you can push files to OS4 by any
other means (SFTP into AmiKit, shared folder, etc.) — the build
artefacts are just regular files.

## 2. Build python-os4

```
git clone https://github.com/geekychris/python-amigaos4.git
cd python-amigaos4

# One-time: pull the walkero cross-compile image + our thin wrapper
docker pull walkero/amigagccondocker:os4-gcc11-arm64   # or amd64
docker build -t amiga-python-build:local .

# Build + strip
scripts/build.sh --strip
```

Output: `build-ppc-amigaos/python-stripped.exe` (~9 MB PowerPC ELF).

Rebuild after editing `_amigamodule.c` / `amiga_shim.c` / `setup.local`:

```
scripts/build.sh --strip     # incremental, ~30-60s
```

Full clean rebuild:

```
scripts/build.sh clean
scripts/build.sh --strip     # ~5-10 min first time
```

## 3. Boot AmigaOS 4.1 FE

Skip if you already have OS4 up.  Otherwise see
[amiga_mcp docs/amigaos4-setup.md](https://github.com/geekychris/amiga_mcp/blob/main/docs/amigaos4-setup.md)
for the QEMU sam460ex install walkthrough.

Once up: verify the `amiga-bridge` daemon is running on OS4 (it
auto-starts from `S:User-Startup` if you followed the setup) — you
should see `AmigaBridge v1.20` in a window on Workbench.

## 4. Deploy python-os4 to OS4 (first time)

`scripts/deploy.sh --stdlib` prints the MCP calls you need.  In
practice, from a Claude Code session with the amiga-devbench MCP:

```
# a) the interpreter
amiga_push_file build-ppc-amigaos/python-stripped.exe DH1:python-os4

# b) stdlib flat files (~7 MB, one-time)
amiga_dos_command  "makedir DH1:lib DH1:lib/encodings DH1:lib/collections \
                     DH1:lib/importlib DH1:lib/json DH1:lib/re DH1:lib/http \
                     DH1:lib/email DH1:lib/logging DH1:lib/urllib \
                     DH1:lib/concurrent DH1:lib/concurrent/futures \
                     DH1:lib/zipfile DH1:lib/zipfile/_path \
                     DH1:lib/ensurepip DH1:lib/ensurepip/_bundled"

amiga_transfer  Python-3.12.7/Lib/*.py               DH1:lib/
amiga_transfer  Python-3.12.7/Lib/encodings/*.py     DH1:lib/encodings/
amiga_transfer  Python-3.12.7/Lib/collections/*.py   DH1:lib/collections/
amiga_transfer  Python-3.12.7/Lib/importlib/*.py     DH1:lib/importlib/
amiga_transfer  Python-3.12.7/Lib/json/*.py          DH1:lib/json/
amiga_transfer  Python-3.12.7/Lib/re/*.py            DH1:lib/re/
amiga_transfer  Python-3.12.7/Lib/http/*.py          DH1:lib/http/
amiga_transfer  Python-3.12.7/Lib/email/*.py         DH1:lib/email/
amiga_transfer  Python-3.12.7/Lib/logging/*.py       DH1:lib/logging/
amiga_transfer  Python-3.12.7/Lib/urllib/*.py        DH1:lib/urllib/
amiga_transfer  Python-3.12.7/Lib/concurrent/*.py    DH1:lib/concurrent/
amiga_transfer  Python-3.12.7/Lib/concurrent/futures/*.py \
                                                     DH1:lib/concurrent/futures/
amiga_transfer  Python-3.12.7/Lib/zipfile/*.py       DH1:lib/zipfile/
amiga_transfer  Python-3.12.7/Lib/zipfile/_path/*.py DH1:lib/zipfile/_path/
amiga_transfer  Python-3.12.7/Lib/ensurepip/*.py     DH1:lib/ensurepip/
amiga_push_file Python-3.12.7/Lib/ensurepip/_bundled/pip-24.2-py3-none-any.whl \
                                                     DH1:lib/ensurepip/_bundled/pip-24.2-py3-none-any.whl

# c) rename out the .zip so zipimport doesn't intercept (broken on this port)
amiga_dos_command "if exists DH1:lib/python312.zip \
                     rename DH1:lib/python312.zip DH1:lib/python312.zip.bak \
                   endif"

# d) our bindings + demos
amiga_dos_command "makedir DH1:pytests/amiga_bindings/amiga/{bridge,dos,exec,intuition,os,pip,turtle} \
                            DH1:pytests/examples \
                            DH1:pytests/{language,stdlib,io,amiga}"

amiga_transfer amiga_bindings/amiga/*.py                DH1:pytests/amiga_bindings/amiga/
amiga_transfer amiga_bindings/amiga/dos/*.py            DH1:pytests/amiga_bindings/amiga/dos/
amiga_transfer amiga_bindings/amiga/exec/*.py           DH1:pytests/amiga_bindings/amiga/exec/
amiga_transfer amiga_bindings/amiga/intuition/*.py      DH1:pytests/amiga_bindings/amiga/intuition/
amiga_transfer amiga_bindings/amiga/bridge/*.py         DH1:pytests/amiga_bindings/amiga/bridge/
amiga_transfer amiga_bindings/amiga/os/*.py             DH1:pytests/amiga_bindings/amiga/os/
amiga_transfer amiga_bindings/amiga/pip/*.py            DH1:pytests/amiga_bindings/amiga/pip/
amiga_transfer amiga_bindings/amiga/turtle/*.py         DH1:pytests/amiga_bindings/amiga/turtle/

amiga_transfer examples/*.py                            DH1:pytests/examples/
amiga_push_file tests/framework.py                      DH1:pytests/framework.py
amiga_transfer tests/language/*.py                      DH1:pytests/language/
amiga_transfer tests/stdlib/*.py                        DH1:pytests/stdlib/
amiga_transfer tests/io/*.py                            DH1:pytests/io/
amiga_transfer tests/amiga/*.py                         DH1:pytests/amiga/
```

## 5. Every boot: set the env vars

**Critical** — without these, Python silently fails at
`init_fs_encoding`.  See [RUNNING.md](RUNNING.md) for the root-cause
diagnosis.

```
amiga_dos_command "setenv PYTHONHOME DH1:"
amiga_dos_command "setenv PYTHONPATH DH1:lib"
```

Persist these across boots by adding to `S:User-Startup`:

```
SetEnv PYTHONHOME DH1:
SetEnv PYTHONPATH DH1:lib
```

## 6. Sanity check

```
amiga_dos_command "DH1:python-os4 --version"
   -> Python 3.12.7

amiga_dos_command "DH1:python-os4 -c \"print(2+2)\""
   -> 4

amiga_push_file  /tmp/hi.py  RAM:hi.py         # your local test script
amiga_dos_command "DH1:python-os4 RAM:hi.py"
```

If any of those produce no output, see the *Diagnosing silent init*
section in [RUNNING.md](RUNNING.md).

## 7. Run a real demo

```
amiga_dos_command "DH1:python-os4 DH1:pytests/examples/clock.py"
```

Should pop a "Python Clock" window on Workbench.  Ctrl-C from the
originating shell won't kill it — click the close gadget or press
ESC.  See [DEMOS.md](DEMOS.md) for the full gallery.

## Updating

New binary only:

```
scripts/build.sh --strip
amiga_push_file build-ppc-amigaos/python-stripped.exe DH1:python-os4
```

New Python-side code (bindings/examples/tests) — no rebuild needed,
just re-`amiga_transfer` the changed files.

## Housekeeping

Long sessions accumulate `ab_script_*` tempfiles in `RAM:T/`.  When
`Info RAM:` starts showing `Free 0` and Python starts silent-failing:

```
amiga_dos_command "delete RAM:T/ab_script_#? RAM:T/ab_sout_#? QUIET"
```

Also delete stale `__pycache__` if you're rebuilding Python and the
old .pyc format-magic won't match:

```
amiga_dos_command "delete ALL DH1:lib/__pycache__ DH1:lib/encodings/__pycache__"
```
