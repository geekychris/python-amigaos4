# AmigaOS 4 shell scripts for python-os4

Ready-to-copy AmigaDOS scripts for setting up and launching either
variant of python-os4. Copy them to your guest via any transfer
method — xdftool, samba, USB, or the amiga_mcp bridge.

## Files

| Script | Purpose | Run when |
| ------ | ------- | -------- |
| `setup-python-os4-newlib` | One-time env config for newlib variant | Once, or add to Startup-Sequence |
| `setup-python-os4-clib4`  | One-time env config for clib4 variant (sets `PYTHONUTF8=1`) | Once, or add to Startup-Sequence |
| `pynewlib`               | Per-invocation launcher — newlib variant | Every time you run python |
| `pyclib4`                | Per-invocation launcher — clib4 variant  | Every time you run python |

## File layout on guest

After installing binaries and running setup scripts:

```
DH1:python-os4-newlib          # newlib interpreter (56 MB stripped: ~15 MB)
DH1:python-os4-clib4           # clib4 interpreter  (49 MB stripped: ~10 MB)
DH1:lib/                       # Python stdlib (shared between variants)
DH1:lib/ssl.py                 # amiga.compat.ssl shim (for clib4)
DH1:lib/amiga/compat/          # ssl_shim source
DH1:pynewlib                   # launcher (this scripts/amiga-scripts/pynewlib)
DH1:pyclib4                    # launcher (this scripts/amiga-scripts/pyclib4)
LIBS:clib4.library             # required for clib4 binary to start (SYSTEM disk)
```

## Setup workflow

Assuming the binaries and stdlib are already on `DH1:`:

```
; on the AmigaDOS shell — one-time setup per variant you want
execute DH1:setup-python-os4-newlib
execute DH1:setup-python-os4-clib4

; verify it works
DH1:pynewlib -V
DH1:pyclib4 -V

; run a script
DH1:pynewlib DH1:some-script.py
DH1:pyclib4 DH1:some-script.py
```

You can add the `execute` lines to `S:User-Startup` so the env vars
persist across reboots.

## Why two variants?

**newlib** — the standard OS4 SDK libc. Broadest compatibility, has
compiled `_ssl` module for HTTPS via stdlib `ssl`.

**clib4** — the modern alternative (github.com/AmigaLabs/clib4).
Wider POSIX surface (pthreads, mmap, dlopen, sockets, wchar).
No stdlib `_ssl` yet (AmiSSL hasn't been ported to clib4), but our
`amiga.compat.ssl_shim` routes `urllib.request.urlopen("https://…")`
through amiga.https (which shells to the standalone openssl binary).

See `../../docs/CLIB4_BUILD.md` for the full story.
