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
