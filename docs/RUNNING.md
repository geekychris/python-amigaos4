# Running Python on AmigaOS 4

## Prerequisites (on OS4 target)

```
python3        # the interpreter (8.9 MB stripped)
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

Symptom: `python3 --help` prints normally, but `python3
RAM:anything.py` produces zero output (script is never reached).

Fix:

```
; setenv PYTHONHOME python3:
; setenv PYTHONPATH python3:lib
```

Set these **once per boot** (or add to `S:User-Startup`) and every
subsequent `python3` invocation works.

Sanity check:

```
python3 RAM:tiny.py
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
amiga_transfer  amiga_bindings/  python3:amiga_bindings/
amiga_transfer  examples/        python3:examples/
```

Try the demos in this order:

```
python3 python3:examples/hello_dos.py
python3 python3:examples/clock.py                   # windowed
python3 python3:examples/window_sysmon.py           # windowed
python3 python3:examples/snake.py                   # turtle game
python3 python3:examples/snake_verifiable.py        # + audit log
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
