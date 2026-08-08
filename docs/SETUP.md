# python-os4 setup — step-by-step per variant

This document walks you through installing and running **either or
both** variants of python-os4 (newlib and clib4) on an AmigaOS 4.1
guest. Follow the variant section that matches what you want; both
variants can coexist on the same guest.

---

## Prereqs (host — where the build runs)

1. Docker for macOS/Linux, arm64 or amd64.
2. The build image, one-time:
   ```bash
   cd python-amigaos4
   docker build -t amiga-python-build:local .
   ```
   Layers walkero's OS4 toolchain + Python 3.12 build-python + clib4
   v2.3 SDK bits (see `Dockerfile`).

## Prereqs (guest — where python-os4 runs)

- AmigaOS 4.1 Final Edition or later (tested against SDK 54.25 +
  dos_sdk 54.136 as of 2026-08).
- QEMU sam460ex machine is a supported test target; real Sam460ex
  hardware should also work but isn't tested.
- ~50 MB free on the boot volume for interpreter + stdlib.
- `LIBS:` writable on the SYS: disk (for the clib4 variant only).

---

## Build both interpreters (on the host)

```bash
./build-all.sh                       # 15–25 min, both variants
```

Or one at a time:
```bash
MCRT=newlib ./build-750.sh make      # newlib only (~10 min)
MCRT=clib4  ./build-750.sh make      # clib4  only (~10 min)
```

Then strip both to shrink the deploy size:
```bash
MCRT=newlib scripts/build.sh --strip
MCRT=clib4  scripts/build.sh --strip
```

Output:
```
build-ppc-amigaos-750/python-stripped.exe          → newlib, ~15 MB
build-ppc-amigaos-750-clib4/python-stripped.exe    → clib4,  ~10 MB
```

## Extract clib4 runtime (only if installing clib4 variant)

```bash
./extract-clib4.sh                    # pulls clib4.library + .so files
# → clib4-runtime/clib4.library       (v2.3 from AmigaLabs release)
# → clib4-runtime/*.so                (unused; keep or ignore)
```

Only `clib4-runtime/clib4.library` is actually needed for python-os4-clib4;
the other files are for downstream programs that dynamically link clib4.

---

## Case A — deploy newlib variant only

### Files you need on the guest

| Source | Destination |
| ------ | ----------- |
| `build-ppc-amigaos-750/python-stripped.exe` | `DH1:python-os4-newlib` |
| `scripts/amiga-scripts/pynewlib`             | `DH1:pynewlib` |
| `scripts/amiga-scripts/setup-python-os4-newlib` | `DH1:setup-python-os4-newlib` |
| `Python-3.12.7/Lib/*` + `python312.zip`      | `DH1:lib/` |

Note: the Python stdlib is variant-independent — one copy in `DH1:lib/`
serves both variants.

### Deploy via `install-on-guest.sh` (amiga_mcp bridge running)

```bash
scripts/install-on-guest.sh newlib
```

### Deploy via `xdftool` (guest offline)

```bash
HDF=~/AmigaOS4/amigaos4-dev.hdf
xdftool $HDF write build-ppc-amigaos-750/python-stripped.exe python-os4-newlib
xdftool $HDF write scripts/amiga-scripts/pynewlib pynewlib
xdftool $HDF write scripts/amiga-scripts/setup-python-os4-newlib setup-python-os4-newlib
# stdlib (pyc.tar bundle if you have make_release.sh output, otherwise
# push each file — many, so bundle-and-extract is preferred)
```

### First run

```
; on the guest
execute DH1:setup-python-os4-newlib     ; sets PYTHONHOME + PYTHONPATH
DH1:pynewlib -V                          ; should print "Python 3.12.7"
DH1:pynewlib -c "print(2 + 2)"           ; should print 4
```

### Persist across reboots (optional)

Add the `setenv` lines from `DH1:setup-python-os4-newlib` to
`S:User-Startup`. From then on, `DH1:pynewlib script.py` works
without running the setup script first.

---

## Case B — deploy clib4 variant only

### Files you need on the guest

| Source | Destination |
| ------ | ----------- |
| `build-ppc-amigaos-750-clib4/python-stripped.exe` | `DH1:python-os4-clib4` |
| `scripts/amiga-scripts/pyclib4`                   | `DH1:pyclib4` |
| `scripts/amiga-scripts/setup-python-os4-clib4`    | `DH1:setup-python-os4-clib4` |
| `Python-3.12.7/Lib/*` + `python312.zip`           | `DH1:lib/` |
| `amiga_bindings/amiga/compat/ssl.py`              | `DH1:lib/ssl.py` |
| `amiga_bindings/amiga/compat/__init__.py`         | `DH1:lib/amiga/compat/__init__.py` |
| `amiga_bindings/amiga/compat/ssl_shim.py`         | `DH1:lib/amiga/compat/ssl_shim.py` |
| `clib4-runtime/clib4.library`                     | `LIBS:clib4.library` (SYS: disk) |

The `ssl.py` shim + `amiga.compat` package are how `import ssl` works
on clib4 (no compiled `_ssl` builtin because AmiSSL isn't ported to
clib4 yet).

### Deploy via `install-on-guest.sh` (amiga_mcp bridge running)

```bash
scripts/install-on-guest.sh clib4
```

### Deploy via `xdftool` (guest offline)

```bash
HDF_DEV=~/AmigaOS4/amigaos4-dev.hdf
HDF_SYS=~/AmigaOS4/amigaos4-system.hdf

# Interpreter + scripts on dev disk
xdftool $HDF_DEV write build-ppc-amigaos-750-clib4/python-stripped.exe python-os4-clib4
xdftool $HDF_DEV write scripts/amiga-scripts/pyclib4 pyclib4
xdftool $HDF_DEV write scripts/amiga-scripts/setup-python-os4-clib4 setup-python-os4-clib4

# ssl shim
xdftool $HDF_DEV write amiga_bindings/amiga/compat/ssl.py       lib/ssl.py
xdftool $HDF_DEV makedir lib/amiga
xdftool $HDF_DEV makedir lib/amiga/compat
xdftool $HDF_DEV write amiga_bindings/amiga/compat/__init__.py  lib/amiga/compat/__init__.py
xdftool $HDF_DEV write amiga_bindings/amiga/compat/ssl_shim.py  lib/amiga/compat/ssl_shim.py

# clib4.library on SYS: disk
xdftool $HDF_SYS write clib4-runtime/clib4.library LIBS/clib4.library
```

### First run

```
; on the guest — MANDATORY
execute DH1:setup-python-os4-clib4    ; sets PYTHONHOME + PYTHONPATH + PYTHONUTF8=1
DH1:pyclib4 -V                         ; should print "Python 3.12.7"
DH1:pyclib4 -c "print(2 + 2)"          ; should print 4
```

### **Important: PYTHONUTF8=1 is required**

Without it, `python-os4-clib4` silently exits at pymain_init with
either `"error evaluating path"` or `"memory allocation failed"`.
Reason: clib4's `setlocale(LC_ALL, "")` returns `"C-ISO-8859-1"`
(newlib returns `"C"`); CPython's `pyconfig_calculate` sizes wchar
buffers based on the locale name and gets confused by clib4's value.
UTF-8 mode bypasses locale-based sizing entirely.

The `pyclib4` launcher sets it automatically. If you invoke the
binary directly (`DH1:python-os4-clib4 …`), you must set the env
var yourself first.

### Persist across reboots (optional)

Add these lines to `S:User-Startup`:
```
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
setenv PYTHONUTF8 1
```

---

## Case C — both variants coexist

Run both `install-on-guest.sh newlib` and `install-on-guest.sh clib4`
(or `install-on-guest.sh` with no args to deploy both). Both binaries
have distinct filenames at `DH1:` root; no conflict.

On the guest:
```
DH1:pynewlib -V    ; runs the newlib variant
DH1:pyclib4  -V    ; runs the clib4 variant
```

For side-by-side testing (e.g. running the smoke test against both
to diff behaviour), see `docs/CLIB4_BUILD.md` "Side-by-side testing".

---

## Verification

`tests/on_guest/smoke.py` is a 30+ probe diagnostic sweep. Run it
against your installed variant:

```
; on the guest
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
assign SMOKE: T:
DH1:pynewlib DH1:smoke.py         ; or DH1:pyclib4 DH1:smoke.py
type T:smoke.log                  ; see all PASS/FAIL lines
```

Expected: 30+ passing tests, a `=== SUMMARY ===` block at the end,
and exit code 0. If anything fails, `T:smoke.log` has enough context
to be forwarded for remote debugging (`docs/CLIB4_BUILD.md` explains
what to look for in the log).

---

## Features you get, per variant

| Feature | newlib | clib4 |
| ------- | :---: | :---: |
| `import ssl` (stdlib)              | ✅ compiled `_ssl` via AmiSSL | ✅ pure-Python shim |
| `urllib.request.urlopen("https://…")` | ✅ | ✅ (transparently via amiga.https) |
| `http.client.HTTPSConnection`       | ✅ | ✅ (same) |
| `requests` / `httpx` / `urllib3`    | ✅ | ❌ (wrap_socket on live socket) |
| `imaplib.IMAP4_SSL` / `smtplib.SMTP_SSL` | ✅ | ❌ (same reason) |
| `hashlib.sha256/md5/sha1/sha512`    | ✅ | ✅ (via HACL builtins) |
| `hashlib.new('blake2b'/'sha3_256')`  | ✅ | ❌ (needs `_hashopenssl`) |
| `hashlib.pbkdf2_hmac`                | ✅ | ❌ (needs `_hashopenssl`) |
| `hmac.new()` (all standard digests)  | ✅ | ✅ (pure-Python fallback on our builtins) |
| `sockets`, `threading`, `sqlite3`   | ✅ | ✅ |
| `amiga.https.fetch()`                | ✅ | ✅ |
| `amiga.pip.install()`                | ✅ | ✅ |
| `amiga.s3` (SigV4 uploads)           | ✅ | ✅ (uses hashlib.sha256 + hmac + amiga.https — all present) |
| C extension `.so` loading (`dlopen`) | ❌ | ❌ (both compiled with `ac_cv_func_dlopen=no`) |

---

## Where to look for more

- `docs/CLIB4_BUILD.md` — full clib4 build story, the PYTHONUTF8 root
  cause, and side-by-side testing recipes.
- `scripts/amiga-scripts/README.md` — details on the launcher scripts.
- `CONTRIBUTING.md` — pre-PR test gates.
- `tests/on_guest/smoke.py` — the diagnostic sweep itself.
