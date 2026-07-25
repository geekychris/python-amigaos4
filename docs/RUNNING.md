# Running Python on AmigaOS 4

## Prerequisites (on OS4 target)

```
DH1:python-os4        # the interpreter (8.9 MB stripped)
DH1:lib/              # stdlib: encodings, os.py, codecs.py, ...
```

## **CRITICAL: environment variables**

Python's built-in `getpath.c` on our OS4 build does **not** discover
`DH1:lib/` automatically from the executable location — the classic
"look for `os.py` next to the binary" heuristic uses POSIX path
separators (`/`) and fails on AmigaDOS volume-relative paths.  You
**must** set both env vars before running any script, or Python dies
silently during `init_fs_encoding` with:

```
ModuleNotFoundError: No module named 'encodings'
```

Symptom: `DH1:python-os4 --help` prints normally, but `DH1:python-os4
RAM:anything.py` produces zero output (script is never reached).

Fix:

```
setenv PYTHONHOME DH1:
setenv PYTHONPATH DH1:lib
```

Set these **once per boot** (or add to `S:User-Startup`) and every
subsequent `DH1:python-os4` invocation works.

Sanity check:

```
DH1:python-os4 RAM:tiny.py
```

where `RAM:tiny.py` is:

```python
print("hello world")
import sys
print("argv:", sys.argv)
```

Expected: `hello world` + `argv: ['RAM:tiny.py']`.

## Debug tooling for the silent-init class of bugs

The interpreter carries three file-based tracers that we leave enabled
so future silent-init failures can be diagnosed without a GDB session:

| tracer                | file             | inserted where                                          |
| --------------------- | ---------------- | ------------------------------------------------------- |
| `pymain_main` stages  | `RAM:pymain.log` | Modules/main.c around `pymain_init` + `Py_RunMain`      |
| every codec lookup    | `RAM:pycodec.log`| Objects/unicodeobject.c `config_get_codec_name`         |
| module init progress  | (add ad-hoc)     | Modules/_amigamodule.c has an `init_trace()` helper     |

When Python silently fails:

1. Check `list RAM:pymain.log` — if empty or missing, Python died
   before `pymain_main` even ran (rare, usually the crt startup).
2. If present, look at `err_msg`/`func` fields.  `init_fs_encoding`
   → check `RAM:pycodec.log` for the failing codec lookup.
3. `RAM:pycodec.log` shows the exact `_PyCodec_Lookup` result plus
   any Python exception (module not found, etc.).

## Once running

Deploy the amiga_bindings tree and the demo apps:

```
amiga_transfer  amiga_bindings/  DH1:pytests/amiga_bindings/
amiga_transfer  examples/        DH1:pytests/examples/
```

Try the demos in this order:

```
DH1:python-os4 DH1:pytests/examples/hello_dos.py
DH1:python-os4 DH1:pytests/examples/clock.py                   # windowed
DH1:python-os4 DH1:pytests/examples/window_sysmon.py           # windowed
DH1:python-os4 DH1:pytests/examples/snake.py                   # turtle game
DH1:python-os4 DH1:pytests/examples/snake_verifiable.py        # + audit log
```

See `docs/DEMOS.md` for screenshots + Mac↔Amiga snake comparison.

## Housekeeping

The AmigaBridge daemon accumulates temp files under `T:` (script
capture, sout).  These live on `RAM:T/` which is a small RAM-disk.
After a long session it fills up.  Clean with:

```
delete RAM:T/ab_script_#? RAM:T/ab_sout_#? QUIET
```

Sign that this bit you: Python starts producing no output where it
did earlier in the same session, `hello-newlib` still works, and
`Info RAM:` shows `Free 0`.
