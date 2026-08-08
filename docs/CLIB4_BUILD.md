# Building python-os4 against clib4 (alongside newlib)

This project can build CPython 3.12 for AmigaOS 4 PPC against **either**
newlib (the default, ships with the OS4 SDK) or **clib4**
(https://github.com/AmigaLabs/clib4 — actively-maintained alternative
libc). Both variants are built from the same source tree, distinguished
by the `MCRT` environment variable and produced into separate output
directories.

The two variants can coexist on a guest and be invoked by name, so you
can compare behavior side-by-side.

## Why clib4?

- Much broader POSIX surface: pthreads, mmap/mprotect, dlopen,
  poll/select, AF_UNIX (emulated), wchar/wctype, SysV IPC (msg/sem/shm),
  aio, iconv, regex, glob, ftw, termios, libresolv, libcrypt.
- Real `enableUnixPaths()` mechanism for Amiga-assign ↔ POSIX-path
  translation — the bug class our newlib shim `amiga_to_posix_path`
  works around may disappear entirely.
- Active development (v2.3 released 2026-07, commits daily) vs the
  frozen-in-time newlib port.

## Why keep newlib?

- Newlib is what everything else on OS4 links against by default. The
  SDK ships it. All existing OS4 binaries and libraries assume it.
- clib4 was historically slower (issue #276, closed but worth
  benchmarking).
- No CPython port has shipped against clib4 before — we're first;
  paper cuts likely.

Keeping both means fallback if a clib4 bug shows up.

## Prereqs

- Docker with the walkero image built into a local layer:
  `docker build -t amiga-python-build:local .`
  (the `Dockerfile` at repo root already targets
  `walkero/amigagccondocker:os4-gcc11`; both `-mcrt=newlib` and
  `-mcrt=clib4` are supported by that image without any rebuild.)

## Build

```bash
# Both variants at once:
./build-all.sh

# Or one at a time:
MCRT=newlib ./build-750.sh make
MCRT=clib4  ./build-750.sh make
```

Output layout:

```
build-ppc-amigaos-750/           # newlib (legacy path preserved)
    python.exe                   # unstripped
    python-stripped.exe          # after scripts/build.sh --strip
    libpython3.12.a              # for GemRB embedding
    libamiga_shim.a
    libamissl_lazy.a
build-ppc-amigaos-750-clib4/     # clib4
    python.exe
    (etc.)
```

Strip either variant with:

```bash
MCRT=newlib scripts/build.sh --strip
MCRT=clib4  scripts/build.sh --strip
```

## Extract clib4 runtime files

clib4 binaries need `clib4.library` in `LIBS:` and a bunch of `.so`
files alongside them. Pull them from the docker image:

```bash
./extract-clib4.sh
# → clib4-runtime/{clib4.library,libc.so,libpthread.so,libcrypt.so,libm.so,
#                  libamiga.so,libstdc++.so,libatomic.so,libssp.so,libobjc.so}
```

## Deploy to guest (via devbench)

If you have amiga_mcp devbench running with the guest booted:

```bash
scripts/install-on-guest.sh          # deploy both variants
scripts/install-on-guest.sh newlib   # newlib only
scripts/install-on-guest.sh clib4    # clib4 only
```

Layout on the guest (single flat drawer, both binaries at DH1: root
— no per-variant directory needed because the binaries are fully
statically linked):

```
DH1:python-os4-newlib          # newlib interpreter        (~15 MB stripped)
DH1:python-os4-clib4           # clib4 interpreter         (~10 MB stripped)
DH1:pynewlib                   # launcher for newlib
DH1:pyclib4                    # launcher for clib4 (sets PYTHONUTF8=1)
DH1:setup-python-os4-newlib    # one-time env setup for newlib
DH1:setup-python-os4-clib4     # one-time env setup for clib4
DH1:lib/                        # Python stdlib (shared)
DH1:lib/ssl.py                  # amiga.compat.ssl shim (used by clib4)
LIBS:clib4.library              # required for any clib4 binary to start (SYS: disk)
```

**Why no per-variant drawer / no bundled `.so` files?** Both binaries
are fully statically linked (`readelf -d` shows "no dynamic section"),
and our build configures `ac_cv_func_dlopen=no`, so no C extensions
load at runtime. The `.so` files that `extract-clib4.sh` produces
(`libc.so`, `libpthread.so`, `libstdc++.so`, etc.) are only relevant
if a downstream binary you build dynamically links against clib4 —
not needed for python-os4-clib4 itself.

## Deploy to guest (manual / no devbench — for Bill and others)

If you're deploying to a guest that doesn't have the amiga_mcp bridge
running (real Sam460ex, or QEMU without the devbench daemon), copy
the files manually. Two paths:

### Path A — via xdftool on the host (QEMU shut down)

```bash
# Both interpreters — flat, no drawers
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    build-ppc-amigaos-750/python-stripped.exe python-os4-newlib
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    build-ppc-amigaos-750-clib4/python-stripped.exe python-os4-clib4

# Launcher scripts — pre-made in scripts/amiga-scripts/
for f in pynewlib pyclib4 setup-python-os4-newlib setup-python-os4-clib4; do
    xdftool ~/AmigaOS4/amigaos4-dev.hdf write scripts/amiga-scripts/$f "$f"
done

# clib4.library on the SYSTEM disk (only for clib4 support)
xdftool ~/AmigaOS4/amigaos4-system.hdf write \
    clib4-runtime/clib4.library LIBS/clib4.library
```

### Path B — via any file transfer (scp, samba, USB, floppy…)

Get these files onto the guest by any means:

```
python-stripped.exe (newlib)  →  DH1:python-os4-newlib
python-stripped.exe (clib4)   →  DH1:python-os4-clib4
scripts/amiga-scripts/*       →  DH1:{pynewlib,pyclib4,setup-python-os4-*}
clib4.library                 →  transfer, then on guest:
                                    copy DH1:clib4.library LIBS: CLONE
```

Then on the guest, run the setup script once per variant:

```
execute DH1:setup-python-os4-newlib
execute DH1:setup-python-os4-clib4
protect DH1:pynewlib rwed
protect DH1:pyclib4  rwed
```

If you want the env vars persistent across boots, paste the `setenv`
lines from `setup-python-os4-*` into `S:User-Startup`.

## Side-by-side testing

The `tests/on_guest/smoke.py` diagnostic sweep runs identically against
both variants and dumps enough context that comparing the two `T:smoke.log`
files highlights any behavior differences. Suggested loop:

```
delete T:smoke_newlib.log T:smoke_clib4.log QUIET

assign SMOKE: T:
DH1:pynewlib DH1:smoke.py
copy T:smoke.log T:smoke_newlib.log

delete T:smoke.log QUIET
DH1:pyclib4 DH1:smoke.py
copy T:smoke.log T:smoke_clib4.log
assign SMOKE: REMOVE
```

Then off the guest, diff:

```bash
curl -s "http://localhost:3000/api/file?path=T:smoke_newlib.log&offset=0&size=131072" | ...  > /tmp/nl.log
curl -s "http://localhost:3000/api/file?path=T:smoke_clib4.log&offset=0&size=131072"  | ...  > /tmp/c4.log
diff /tmp/nl.log /tmp/c4.log | less
```

The header block of each log dumps mounted assigns, environment, guest
version — everything needed to correlate a variant's behavior with the
runtime state.

## What to look for

Diffs to watch for between the two logs:

- **assign_visibility_matrix**: newlib and clib4 agree on which volumes
  they can see (if they don't, clib4 is doing something different at
  ELF-load time — worth investigating).
- **write_visible_each_assign**: whether the phantom-FS class shows up
  for clib4 the way it did for newlib. Hypothesis: clib4 doesn't have
  the bug at all; if that's true, we can retire the whole path-
  translation shim on clib4 (already gated behind `#ifndef __CLIB4__`
  in amiga_shim.h).
- **read_prefix_forms**: newlib rejects `/T/foo`; unclear what clib4
  accepts. The log will show.
- **stat_matrix + assign_visibility_matrix** together give a full
  picture of what paths each runtime understands.

## Known limitations & open questions

- `clib4.library` version compatibility: the library in `LIBS:` must be
  newer than what the binary was linked against, or the binary won't
  start. If a version mismatch shows up, `extract-clib4.sh` gets you a
  fresh copy from the docker image (currently v2.3-based).
- Open clib4 bug #448: dlopen crashes on first call under GCC 13. We're
  on GCC 11 so should be safe, but flag if you see it.
- clib4 has no `fork()` — same as newlib. CPython's `subprocess`
  module will not fully work in either variant; nothing new to worry
  about here.
- SSL still via AmiSSL (unchanged). `install-amissl-on-os4.sh` is
  variant-independent.

## When something breaks

The clib4 build is new. Below are issues discovered on the first pass;
all are already fixed in-tree, listed here so a future maintainer knows
what patterns to look for.

### Compile-time issues already fixed

1. **`SA_ONSTACK undeclared`** in `Python/pylifecycle.c` — clib4's
   `signal.h` doesn't declare it (no sigaltstack support). Fixed by
   `#define SA_ONSTACK 0` in `amiga_shim.h` when not already defined.
2. **`struct tm` has no `tm_zone` / `tm_gmtoff`** in
   `Modules/_datetimemodule.c` — clib4 spells them `__tm_zone` /
   `__tm_gmtoff` (BSD-hidden). Fixed by setting
   `ac_cv_member_struct_tm_tm_{zone,gmtoff}=no` in the configure line
   so CPython compiles the fallback branch using the `timezone` global.
3. **`expected identifier before '(' token` on `state->NO_TTINFO.tzname`
   in `Modules/_zoneinfo.c`** — clib4's `time.h` defines `tzname` as a
   macro. `#undef tzname` (and `timezone`, `daylight`) in
   `amiga_shim.h` restores use of the identifier as a field name.
4. **`OPENSSL_THREADS is not defined`** in `Modules/_ssl.c` — clib4's
   openssl include chain doesn't always pull in the `configuration.h`
   header where AmiSSL declares OPENSSL_THREADS. Fixed by adding
   `-DOPENSSL_THREADS=1` to `CFLAGS_BASE` when `MCRT=clib4` (AmiSSL
   is thread-safe, so the assertion is truthful).

### Warning noise you can safely ignore

- `warning: "_POSIX_THREADS" redefined` — clib4 defines it as an empty
  macro (POSIX signal); pyconfig defines it to `1`. Semantically
  identical, harmless.
- `warning: "__BSD_VISIBLE" redefined` — clib4's `features.h` defines
  it as `0`; pyconfig defines it to `1`. Determines whether some
  BSD-only prototypes are visible; the pyconfig value wins for
  CPython's needs.
- `warning: "le64toh" / "htole64" redefined` — endian macros collide
  between clib4's `endian.h` and CPython's HACL crypto headers. The
  two definitions are semantically identical (`__bswap_64(x)`), so
  harmless.

### Current build state (2026-08-07)

**Toolchain**: extended walkero image, upgraded from clib4 v2.1 (shipped
with `walkero/amigagccondocker:os4-gcc11`) to **clib4 v2.3** — the
Dockerfile pulls Andrea Palmatè's official .deb release and drops the
new SDK bits into the walkero SDK tree. Guest-side `clib4.library` v2.3
is downloaded from the matching LHA release by `extract-clib4.sh`.

**Both variants build cleanly:**

```
build-ppc-amigaos-750/python.exe          56 MB   (newlib, with stdlib ssl)
build-ppc-amigaos-750-clib4/python.exe    49 MB   (clib4, no stdlib ssl)
clib4-runtime/                            10 files (30 MB, mostly libstdc++.so)
```

**Both variants are functionally equivalent for our stack, and both
have HTTPS available via different paths:**

- **newlib variant**: `import ssl` uses the real compiled `_ssl` module
  linked against AmiSSL (lazy-init via amissl_lazy.c).
- **clib4 variant**: `import ssl` uses `amiga.compat.ssl_shim` (shipped
  as `DH1:lib/ssl.py`), which monkey-patches `http.client.HTTPSConnection`
  to route through amiga.https (openssl binary shell-out). So
  `urllib.request.urlopen("https://…")` and `http.client.HTTPSConnection`
  transparently work on both variants.
- Direct `amiga.https.fetch()` calls work identically on both.
- `amiga.pip` and `amiga.s3` build on `amiga.https` — full feature
  parity on both variants.
- `hashlib.md5/sha1/sha256/sha512` etc. work via our HACL-based
  built-in modules (`_md5`, `_sha1`, `_sha2` from `setup.local`),
  no OpenSSL needed on either variant.

**What still doesn't work on clib4 that DOES work on newlib:**

- Raw-socket TLS upgrade patterns: `SSLContext.wrap_socket(sock)`.
  Impacts third-party libraries built on urllib3 / requests / httpx
  (they upgrade a live socket) and stdlib `imaplib.IMAP4_SSL` /
  `smtplib.SMTP_SSL`. Not fixable without a real ssl library binding
  or upstream AmiSSL clib4 support (`libamisslauto.a` missing).
- `hashlib.new('blake2b'/'sha3_256')` and `hashlib.pbkdf2_hmac` —
  need the OpenSSL-backed `_hashopenssl` module.

**What clib4 loses:**

- `import ssl` (stdlib) — no TLS via stdlib. Third-party libraries
  that do `import ssl` directly (requests, urllib3, aiohttp, etc.)
  will fail. `urllib.request` for HTTPS URLs will also fail.
- OpenSSL-backed hashlib extras: `hashlib.new('blake2b')`,
  `hashlib.new('sha3_256')`, `hashlib.pbkdf2_hmac()`. Standard
  digest names (`md5`, `sha1`, `sha256`, etc.) keep working via
  our built-ins.

If any of that matters for your workflow, use the newlib variant.

### Upstream blockers not yet fixed

- **`libamisslauto.a` missing for clib4**. AmiSSL ships an auto-init
  helper only for newlib and clib2 (see
  `/opt/ppc-amigaos/ppc-amigaos/SDK/local/{newlib,clib2}/lib/libamisslauto.a`).
  There is no `clib4/lib/libamisslauto.a`. The link step fails with
  `ld: cannot find -lamisslauto`.

  This is genuinely upstream — AmiSSL needs to port its auto-init to
  clib4. Workarounds:
  - Skip `_ssl` and `_hashopenssl` from Modules/Setup.local for clib4
    builds (loses HTTPS from the clib4 variant — but everything else
    including sockets works).
  - Wait for AmiSSL to ship libamisslauto for clib4.
  - Handroll an amissl_lazy.c equivalent for clib4 that works around
    the openssl3-header parse cascade (see below).

- **amissl_lazy.c can't compile under clib4**. Its use of
  `<proto/amissl.h>` pulls in openssl3 headers whose ASN.1 macros
  (`DECLARE_ASN1_DUP_FUNCTION`) triggers a GCC "old-style parameter
  declaration" parse cascade. Not clear whether the fix is in clib4's
  openssl3 headers or in the ASN.1 macro definitions. For now the
  build system substitutes a dummy `libamissl_lazy.a` for clib4 and
  routes SSL through `-lamisslauto` — which fails at link because of
  the point above. Currently blocked here.

### Runtime issues (once the build succeeds)

1. **Missing `clib4.library`** — binary won't start. Copy the file
   from `extract-clib4.sh` output into `LIBS:`.
2. **Missing `libc.so` etc alongside the binary** — same. The install
   script places them in `DH1:python-os4-clib4/`.
3. **`clib4.library version mismatch`** — the library in `LIBS:` must
   be at least as new as what the binary was linked against.
   `extract-clib4.sh` always pulls the same version the docker image
   linked with, so extracting and re-deploying together should never
   trip this.
4. **Runtime crash on startup** — capture `amiga_last_crash` via
   amiga_mcp or read the `GrimReaper` info from the crash dialog.

Ship us the failure via `T:smoke.log` (see the smoke's own trailer for
what to include) and the crash log if any.

## Runtime debugging progress (2026-08-07 session)

Confirmed: **clib4 v2.3 itself works fine on our QEMU guest** —
a static hello-world (`hello.c` compiled with `-mcrt=clib4 -athread=native
-lauto`) prints normally and exits with the expected return code. So
clib4.library v2.3 in `LIBS:` and the runtime linkage are correct.

**The blocker is CPython-specific.** The `pymain.log` tracer Bill added
to `Modules/main.c` captures where init fails:

Without `PYTHONEXECUTABLE`:
```
A: enter pymain_main
B: after pymain_init exitcode=0 exception=1
  err_msg: error evaluating path
  func:    (none)
```

With `PYTHONEXECUTABLE=DH1:python-os4-clib4/python-os4`:
```
A: enter pymain_main
B: after pymain_init exitcode=0 exception=1
  err_msg: memory allocation failed
  func:    (none)
```

Interpretation: CPython's `pyconfig_calculate` (invoked from
`Py_InitializeFromConfig`) fails when it tries to resolve wide-char
paths on clib4. The first form fails at the resolution itself; the
second progresses past resolution but then fails on a wide-char
allocation (probably `_Py_wcsdup` or `mbstowcs`).

The same code works on newlib, which suggests clib4's `mbstowcs` /
`realpath` / wchar handling differs from newlib in a way our frozen
`getpath.py` can't tolerate. Not a bug in *our* code — an interop
issue between CPython's assumptions and clib4's POSIX surface.

**Paths forward** (roughly ordered by effort):

1. **Patch pymain to hardcode paths for clib4** — instead of calling
   `pyconfig_calculate`, set `sys.executable`/`sys.prefix`/etc.
   directly from compile-time constants when `__CLIB4__` is set.
   Modest patch to `Modules/main.c` or `Python/initconfig.c`.

2. **Bug-report to clib4** — file an issue at
   https://github.com/AmigaLabs/clib4 with a minimal reproducer
   (CPython does `mbstowcs("DH1:python-os4-clib4/python-os4", buf, N)`
   or similar). May be fixed in v2.4.

3. **Attach GDB via QEMU gdbstub** (per `gdb_qemu_available.md`
   memory) — set a breakpoint on `_PyStatus_ERR` or wcsdup, catch
   the specific failing call, work backwards.

4. **Swap clib4's `libdebug.so` for `libc.so`** in the deployed
   binary directory — the debug variant prints init traces (though
   might not help since it's a static build).

## THE FIX: PYTHONUTF8=1 (2026-08-07)

Debugged with a `wchar-probe.c` reproducer that tests mbstowcs /
realpath / wcsdup / setlocale on both variants. All wchar operations
pass identically — **except** `setlocale(LC_ALL, "")`:

- **newlib:** returns `"C"`
- **clib4:**  returns `"C-ISO-8859-1"`

CPython's `pyconfig_calculate` uses the locale return value to
compute wchar buffer sizes. On clib4's non-standard locale name it
sizes the buffer wrongly, so the follow-up `mbstowcs` / `wcsdup`
call fails silently — resulting in `pymain_init` returning either
`"error evaluating path"` or `"memory allocation failed"`.

**Fix:** `setenv PYTHONUTF8 1` — enables UTF-8 mode which bypasses
the locale-based wchar sizing entirely. CPython then uses fixed
UTF-8 encoding for all path/env conversions.

`install-on-guest.sh` injects this env var into the clib4 wrapper
script (`DH1:pyclib4`). Newlib doesn't need it.

Verified end-to-end: `DH1:python-os4-clib4/python-os4 -c "print('alive')"`
returns rc=0 and prints `alive` when PYTHONUTF8=1 is set.

Task #153 done — the previously mysterious clib4 silent-init failure
is a locale-return-value interop issue, worked around cleanly by
PYTHONUTF8=1 in the launcher.
