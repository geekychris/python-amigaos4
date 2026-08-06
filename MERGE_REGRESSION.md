# Post-merge regression report — 2026-08-06

**Merge:** `origin/enhancements` (32 commits, Bill's branch) into `main`
at commit `466a9cd`, then build-750.sh fix `8326ec7`.

## Summary

Build works. Basic invocation works. **Any file-arg or `-c` invocation
of the new `python-os4` binary dies silently before printing anything.**

## What was verified working

| Test | Result |
| ---- | ------ |
| `git merge origin/enhancements` (one conflict on `autoinstall`, resolved to theirs — strict superset) | ✅ merged clean |
| `./scripts/build.sh --strip` (after fixing `build-750.sh` bugs in `8326ec7`) | ✅ produces 15 MB `python-stripped.exe` |
| 45 offline `amiga.pip.*` unit tests | ✅ all pass |
| Deploy `python-stripped.exe` → `DH1:python-os4` via xdftool | ✅ |
| Deploy Bill's stdlib patches (mmap.py, pyexpat.py, plistlib.py, posixpath.py, hashlib.py, site.py, subprocess.py, sysconfig.py, _sysconfigdata__amigaos_.py, _sysconfigdata__amigaos4_.py, site-packages.pth) → `DH1:lib/` | ✅ |
| Deploy fresh `amiga.pip` package → `DH1:lib/amiga/pip/` | ✅ |
| `python-os4 -V` on-guest | ✅ prints `Python 3.12.7` |

## What broke

| Test | Result |
| ---- | ------ |
| `python-os4 -c "print('hello')"` | ❌ no stdout, no stderr, no crash captured, process exits silently |
| `python-os4 DH1:mock_install.py` | ❌ same — no output, no `T:mockrun.log` produced (first line of that script writes it), process exits silently |
| `python-os4 -v -c "print('hello')"` | ❌ verbose-import diagnostics never appear in either stdout or stderr |
| `T:pymain.log` (tracer at top of `pymain_main` in Modules/main.c) | ❌ never gets written on ANY invocation — including `-V`, which we know reaches `pymain_main` |

## Diagnostic evidence

The critical anomaly: **`T:pymain.log` is empty after every run,
including the `-V` run that we know reached the interpreter**. That
tracer is a `fopen("T:pymain.log", "w")` at the very first line of
`pymain_main` (Modules/main.c:736).

For it to stay empty when `pymain_main` DID run and print
`Python 3.12.7`, only one thing fits: **`fopen("T:pymain.log", "w")`
is returning NULL**. That points squarely at Bill's new
`amiga_fopen` shim in `amiga_shim.c` — the `-include amiga_shim.h`
in the build flags macros every `fopen` in the source tree to
`amiga_fopen`, which does:

```c
FILE *amiga_fopen(const char *filename, const char *mode) {
    char pbuf[1024];
    return fopen(amiga_to_posix_path(filename, pbuf, sizeof(pbuf)), mode);
}
```

`amiga_to_posix_path("T:pymain.log", ...)` produces `/T/pymain.log`.
If newlib on this OS4 build doesn't map `/T/...` back to `T:...`
correctly, `fopen` returns NULL. That silences the tracer AND
breaks any file-arg mode of Python (loading the script file also
goes through `fopen`).

Why does `-V` still work? Because `-V` never opens a file — it
prints via `write()` to stdout, which the shim doesn't touch.

## Suspected fault

`amiga_fopen` (and by extension `amiga_open`, `amiga_stat`, etc.)
translate Amiga volume paths (`T:foo`) to POSIX-with-leading-slash
(`/T/foo`), which is the newlib-expected form on some OS4 builds
but apparently **not** this one. The forward translation kills
every fopen with a volume-prefixed path.

## Confirming the theory

Two ways to prove or refute this, neither attempted this session:

1. **Rebuild without `-include amiga_shim.h`** (or with a shim that's
   a no-op passthrough). If file-arg Python then works, the shim
   is the culprit.

2. **Point `fopen` at an already-POSIX path** — modify main.c's
   tracer to `fopen("/T/pymain.log", "w")` (bypasses the shim's
   translation). If the file appears, `/T/...` works and the fault
   is elsewhere. If it doesn't, newlib on this build doesn't
   support the `/T/foo` form at all and the shim's translation
   is a net-negative.

## Recommended follow-up

Bill's shim is designed to fix a real bug — before it, Python
would silently corrupt volume paths like `python3:lib` into
`/ython3:` (per his commit `130d850`). So the fix is directionally
correct. But the specific `/{VOL}/{path}` output form may need
adjustment for this newlib version.

Suggested actions, in order:

1. Ask Bill: was `build-750.sh` tested end-to-end against a
   guest, or only up to producing python-stripped.exe? The
   regression may already be known.
2. Compile a tiny C program that fopens both `T:test.txt` and
   `/T/test.txt` (linked against Bill's amiga_shim.a) — see which
   returns NULL. That definitively answers whether `/T/...` is
   the right form.
3. If `/T/...` is wrong, try `RAM:T/foo` as the translation
   target for T-drawer paths, or leave `T:foo` untouched if the
   colon is present (i.e., only translate when path starts with
   a volume-name that doesn't already have `:`).

## Current state on disk

Guest disk `amigaos4-dev.hdf`:
```
DH1:python-os4                      15196692 bytes  (new binary, works for -V)
DH1:lib/mmap.py                     (Bill's stub)
DH1:lib/pyexpat.py                  (Bill's stub)
DH1:lib/plistlib.py                 (Bill's patched version)
DH1:lib/posixpath.py                (Bill's patched version)
DH1:lib/hashlib.py                  (Bill's patched version)
DH1:lib/site.py                     (Bill's patched version)
DH1:lib/subprocess.py               (Bill's patched version)
DH1:lib/sysconfig.py                (Bill's patched version)
DH1:lib/_sysconfigdata__amigaos_.py
DH1:lib/_sysconfigdata__amigaos4_.py
DH1:lib/site-packages.pth
DH1:lib/amiga/pip/                  (my install-flow module — unaffected)
DH1:{mock_install.py, chardet.whl, chardet.json, mock_run.script}  (fixtures)
```

Host repo `python-amigaos4/` at `main = 8326ec7`, clean.

---

## Update after `d8368f3` shim-fallback fix

Applied fallback (try /VOL/path first, fall back to VOL:path on
NULL) to every path-translating shim in amiga_shim.c.

**Fixed by fallback:**
- `python-os4 -c "print('hello')"` — was silently broken, now works
- pymain.log tracer would presumably fire too (didn't retest)

**Still broken (deeper investigation needed):**
- `python-os4 T:tiny.py` and `python-os4 DH1:tiny.py` —
  process runs and EXITS CLEANLY (no error to stderr, no crash),
  but the script body never actually executes. `tiny.py` is
  `open('T:tiny.log','w').write('hello from tiny\n')` and
  T:tiny.log is not created.
- Even `python-os4 -c "f=open('T:x','w'); f.write('via_close'); f.close(); print('ok')"`
  prints `ok` (via stdout redirect) but T:x is not created.
- Even `python-os4 -c "import os; fd=os.open('T:o','wc',...); os.write(fd,b'x'); os.close(fd); print('osopen_ok')"`
  prints `osopen_ok` but T:o is not created.

**Interpretation:** every file-write from user Python code is
silently discarded. `os.open` returns a valid-looking fd,
`os.write` returns bytes-written, `os.close` succeeds — but no
file appears on disk. Not a NULL fd (the fallback would catch
that). Something like: newlib's `open("/T/foo", O_WRONLY|O_CREAT)`
returns an fd pointing at a hidden/virtual location that AmigaDOS
`list` doesn't see, or `open` succeeds but data is buffered
without ever flushing to the real file.

**File-arg mode (`python-os4 script.py`) failure is the same class:**
Python opens the script, reads back 0 bytes (or something invisible),
compiles nothing, exits normally. No user code runs. Both -V and
`-c print` still work because they don't need Python's file I/O.

**Suggested next debug step:** compile stock CPython's Python/fileutils.c
(revert Bill's `b2fe098`) into a new build. If write-to-file then
works, the bug is in Bill's fileutils.c edits (specifically
`_Py_normpath_and_size`). If write still doesn't work, the bug is
in amiga_shim's translation returning fds that don't correspond
to real files on disk.

Second option worth trying: add a printf to `amiga_open`'s
success path to log the translated path + returned fd. Run any
file-write test and inspect the log to see EXACTLY where newlib
thinks the file lives.

---

## Update after fileutils.c bisect (still `f402c7d`-class state)

**Bisect result: Bill's fileutils.c is NOT the cause.**

Replaced Bill's `Python/fileutils.c` with stock CPython 3.12.7,
rebuilt, deployed. Same behavior:
- `python-os4 -V` prints version ✓
- `python-os4 -c "print"` prints ✓
- `python-os4 tiny.py` where tiny.py is `open('T:x','w').write('y')`
  — completes normally but NO FILE is created ✗

So Bill's `_Py_normpath_and_size` edits are innocent. Restored
his fileutils.c.

**Also tried:** changing `amiga_to_posix_path` from `/VOL/path`
to `/VOL:path` (Bill's earlier commit `602c5ac` form — leading
slash but colon preserved). That form made things WORSE — even
`-c "print"` stopped producing output. Reverted.

**Confirmed suspect: `amiga_open` returns valid-looking fds that
don't correspond to real disk files.** The shim's `open(tp, ...)`
call succeeds where `tp = "/T/foo"` (newlib accepts the form
but writes go into a virtual/hidden location that AmigaDOS
`list` doesn't see). Fallback doesn't fire because open
succeeded. Every user-code file write silently discarded.
Every user-code file read gets 0 bytes.

**What actually needs to happen (not doable this session):**

1. Bill's `amiga_open` needs a post-open `fstat` check — if the
   fd points at a file with no size and the write should have
   created content, retry with the untranslated path.

2. OR: `amiga_to_posix_path` should be smarter about which
   paths NEED translation (probably only when the volume name
   is a python3-style ASSIGN that newlib mishandles), leaving
   plain volume paths like `T:foo` alone.

3. OR: use `IDOS->NameFromFH(fh)` after open to verify the
   file was actually created at the expected location.

Any of these needs Bill's input on what he was trying to fix
originally.

## Regression suite added

`tests/on_guest/smoke.py` — 10-probe minimum-viable regression
sweep that would have caught this on the first deploy attempt.
Includes `write_file_via_open` and `write_file_via_os_open` as
independent probes — either one would have flagged the bug
with a specific failure message.
