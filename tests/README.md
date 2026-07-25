# python-amigaos4 test suite

Suite that runs on **real OS4 PPC** (via QEMU sam460ex + amiga-devbench bridge).
Every test file uses `framework.py` and prints a single final line the runner
grep's for:

```
PASS: <name>  (K/N)
FAIL: <name>  (K/N passed)   ← plus per-check diagnostics
SKIP: <name>  (why)
```

## Layout
- `framework.py` — tiny test runner (`TestRunner.check/check_eq/section/run`).
  Installs a `sys.excepthook` so uncaught exceptions become `FAIL:` lines
  instead of silent-exiting (Amiga port quirk).
- `language/` — pure-language checks (arithmetic, strings, control flow,
  classes, iterators, exceptions).
- `stdlib/` — modules that need static C extensions (math, json, re,
  collections, itertools, functools, datetime).
- `io/` — file I/O against `RAM:` on the target.
- `amiga/` — probes the `amiga_bindings/` package (currently every stub
  raises `NotImplementedYet` — flips to real `PASS:` as Phase 6 lands).

## Running

The runner IS the amiga-devbench MCP session. From the amiga_mcp repo
with a live bridge over TCP (see `scripts/start-qemu-os4.sh --net`):

```
# 1. Bulk-push stdlib + tests (once per Python build)
amiga_transfer  Python-3.12.7/Lib/*.py           DH1:lib/
amiga_transfer  Python-3.12.7/Lib/importlib/*.py DH1:lib/importlib/
amiga_transfer  Python-3.12.7/Lib/collections/*.py DH1:lib/collections/
amiga_transfer  Python-3.12.7/Lib/json/*.py     DH1:lib/json/
amiga_transfer  Python-3.12.7/Lib/re/*.py       DH1:lib/re/

amiga_transfer  tests/framework.py              DH1:pytests/framework.py
amiga_transfer  tests/language/*.py             DH1:pytests/language/
amiga_transfer  tests/stdlib/*.py               DH1:pytests/stdlib/
amiga_transfer  tests/io/*.py                   DH1:pytests/io/
amiga_transfer  tests/amiga/*.py                DH1:pytests/amiga/
amiga_transfer  amiga_bindings/                 DH1:pytests/amiga_bindings/

# 2. Run every test
amiga_dos_command "DH1:python-os4 DH1:pytests/language/01_arithmetic.py"
# ... repeat for each file, or wrap in a small shell loop from an
#     MCP-enabled Claude session.
```

## Current status (Jul 2026)

| section  | tests | checks | status  |
| -------- | ----- | ------ | ------- |
| language | 8     | 193    | PASS    |
| stdlib   | 3     | 73     | PASS    |
| io       | 1     | 19     | PASS    |
| amiga    | 1     | 13     | PASS (stubs) |
| **total**| **13**| **298**| **PASS** |
