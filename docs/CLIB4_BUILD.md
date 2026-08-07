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

Layout on the guest:

```
DH1:python-os4-newlib/
    python-os4                # newlib-linked interpreter
DH1:python-os4-clib4/
    python-os4                # clib4-linked interpreter
    libc.so                   # clib4's libc — MUST live next to the exe
    libpthread.so             # (all .so files bundled here)
    libcrypt.so
    ...
DH1:pynewlib                  # wrapper script — invokes newlib variant
DH1:pyclib4                   # wrapper script — invokes clib4 variant
LIBS:clib4.library            # required for any clib4 binary to start
```

**Why per-variant drawers?** Both newlib and clib4 ship a `libc.so`.
Dropping both into `SOBJS:` would break one of the two. The OS4 ELF
loader searches `PROGDIR:` before `SOBJS:`, so binding each `.so` next
to its own binary keeps them isolated.

## Deploy to guest (manual / no devbench — for Bill and others)

If you're deploying to a guest that doesn't have the amiga_mcp bridge
running (e.g. a real Sam460ex, or a QEMU without the devbench daemon),
copy the files manually. Two paths:

### Path A — via xdftool on the host (QEMU shut down)

```bash
# Newlib variant
xdftool ~/AmigaOS4/amigaos4-dev.hdf makedir python-os4-newlib
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    build-ppc-amigaos-750/python-stripped.exe python-os4-newlib/python-os4

# Clib4 variant
xdftool ~/AmigaOS4/amigaos4-dev.hdf makedir python-os4-clib4
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    build-ppc-amigaos-750-clib4/python-stripped.exe \
    python-os4-clib4/python-os4
for so in clib4-runtime/*.so; do
    xdftool ~/AmigaOS4/amigaos4-dev.hdf write "$so" \
        "python-os4-clib4/$(basename $so)"
done

# The clib4.library needs to go into LIBS: on the SYS: volume.
# Different HDF file — same idea:
xdftool ~/AmigaOS4/amigaos4-system.hdf write \
    clib4-runtime/clib4.library LIBS/clib4.library
```

### Path B — via any file transfer (scp, samba, USB, floppy…)

Get these files onto the guest by any means:

```
python-stripped.exe (newlib)         → DH1:python-os4-newlib/python-os4
python-stripped.exe (clib4)          → DH1:python-os4-clib4/python-os4
libc.so + libpthread.so + libcrypt.so + libm.so
    + libamiga.so + libstdc++.so + libatomic.so + libssp.so
                                     → DH1:python-os4-clib4/*.so
clib4.library                        → transfer, then on guest:
                                         copy DH1:clib4.library LIBS: CLONE
```

Then on the guest, create wrappers:

```
; DH1:pynewlib — save as this file
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
DH1:python-os4-newlib/python-os4 $@
```

```
; DH1:pyclib4 — save as this file
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
DH1:python-os4-clib4/python-os4 $@
```

Make both wrappers executable:

```
protect DH1:pynewlib rwed
protect DH1:pyclib4  rwed
```

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
