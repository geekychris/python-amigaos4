# Contributing to python-amigaos4

Bill's stated end-goal is a **static `libpython.a` + SDK + amiga_shim
+ amissl support** for **GemRB** to embed. `python-os4` as an
interactive interpreter is a side effect that verifies the pieces
work together, not the primary deliverable. That should shape what
"broken" means for a change: if `libpython.a` links cleanly and
`Py_Initialize()` succeeds from an embedded host, most PRs are OK
even if some interactive-shell paths regress.

## Pre-PR checklist

Run these in order. Do not skip. Each has caught a bug once already.

### 1. Offline unit tests (host, ~1 second)

```bash
python3 tests/test_pip_resolver.py
python3 tests/test_pip_cache.py
python3 tests/test_pip_install.py
python3 tests/test_s3_signer.py
```

Every one must print `OK` at the end. 46+ tests total; runs on any
Python 3.11+ with `certifi` installed.

**Catches:** resolver / cache / install-orchestrator regressions,
regressions to canonical name handling, dep-walk semantics.
**Doesn't catch:** anything in C-side code or shim behaviour.

### 2. Docker cross-compile smoke (host, ~10 minutes)

```bash
rm -rf build-ppc-amigaos-750
./scripts/build.sh --strip
```

Confirm:
- `build-ppc-amigaos-750/python.exe` exists (~56 MB unstripped)
- `build-ppc-amigaos-750/python-stripped.exe` exists (~15 MB)
- `build-ppc-amigaos-750/libpython3.12.a` exists (~55 MB) **← the
  GemRB deliverable**
- `build-ppc-amigaos-750/libamiga_shim.a` exists
- `build-ppc-amigaos-750/libamissl_lazy.a` exists

If the build itself doesn't complete: red flag, do not proceed.

If build completes but any of the above are missing: shim
compilation problem or strip script broken — fix before
continuing.

**Catches:** compile errors, link failures, `build-750.sh`
regressions, missing symbol errors when linking libpython.a.

### 3. Guest deploy + on-guest smoke sweep (~5 minutes)

```bash
# stop QEMU
pkill -9 -f qemu-system-ppc
sleep 2

# deploy binary + fresh smoke script
xdftool ~/AmigaOS4/amigaos4-dev.hdf delete python-os4
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    build-ppc-amigaos-750/python-stripped.exe python-os4
xdftool ~/AmigaOS4/amigaos4-dev.hdf delete smoke.py 2>/dev/null
xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
    tests/on_guest/smoke.py smoke.py

# boot
~/code/claude_world/amiga_mcp/scripts/start-qemu-os4.sh \
    --gdb --gdb-port 4433 &

# wait for guest bridge tick >= 8, silent < 3, then:
cat > /tmp/smoketest.script <<'EOF'
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
DH1:python-os4 DH1:smoke.py >T:sm.out 2>T:sm.err
echo done_smoke >T:sm.done
EOF
curl -s -X POST http://localhost:3000/api/transfer \
    -H 'Content-Type: application/json' \
    -d '{"source":"/tmp/smoketest.script","dest":"T:smoketest.script","direction":"push"}'
curl -s -X POST http://localhost:3000/api/launch \
    -H 'Content-Type: application/json' \
    -d '{"command":"execute T:smoketest.script"}'

# wait ~30s, then read the log:
curl -s "http://localhost:3000/api/file?path=T:smoke.log&offset=0&size=16384" \
    | python3 -c 'import sys,json,binascii;h=json.load(sys.stdin).get("hexData","");\
                  print(binascii.unhexlify(h).decode("latin-1",errors="replace"))'
```

Expected end of smoke.log:

```
=== SUMMARY ===
  CORE        : 12/12 pass  [OK]
  EMBED       : 5/5 pass    [OK]
  INTEGRATION : 6/6 pass    [OK]
```

The `smoketest.script` should include `assign SMOKE: T:` before invoking
`python-os4` — the `custom_assign_write` probe uses it to guarantee a
non-native assign is always in the tested set, even on guests where
`python3:` isn't mounted. Full wrapper:

```
setenv PYTHONHOME DH1:
setenv PYTHONPATH "DH1:lib"
assign SMOKE: T:
DH1:python-os4 DH1:smoke.py >T:sm.out 2>T:sm.err
assign SMOKE: REMOVE
echo done_smoke >T:sm.done
```

Smoke test exit codes (from stdout `sm.out`):
- **0** — all tiers green, safe to PR
- **1** — CORE failure, DO NOT PR (interpreter unusable)
- **2** — EMBED failure, DO NOT MERGE (libpython.a integration broken)
- **3** — INTEGRATION failure, release-notes only (pip/ssl surface degraded)

**Catches:** silent-fopen-fail (write_file_via_open probe), path
translation regressions (read_own_write probe — verifies file
lands where AmigaDOS `list` can see it), threading, gc, C-ext
loading, ssl init, socket creation, amiga.pip package integrity.

## What each tier signals

**CORE** — the guest interpreter can load an interpret Python code
at all. If this fails, **libpython.a is also broken** for GemRB
because these tests exercise the same startup path. Never merge if
a CORE test fails.

**EMBED** — capabilities GemRB (or any C host) will hit through
the embedding API: threading, gc, C-extension import, exception
handling, unicode. A failure here means GemRB won't work even if
the interactive interpreter does.

**INTEGRATION** — pip, HTTPS, SSL. Failures here mean users can't
install packages or make network calls, but the core interpreter
still works. Fine to ship with these regressions as long as the
release notes call it out.

## When a change breaks CORE

The regression from the merge session (the one this file exists
because of): `write_file_via_open` failed because
`amiga_shim.c:amiga_open` was returning fds pointing at a virtual
newlib location that AmigaDOS `list` couldn't see. Root cause was
the order in the fallback: it tried the translated `/VOL/path`
form first, then fell back to `VOL:path`. For assigns that newlib
knows about natively (T:, RAM:, SYS:, DH0-9), newlib silently
"succeeded" on `/VOL/path` but wrote into a virtual filesystem.
Reversing the order (try `VOL:path` first) fixes it.

See `MERGE_REGRESSION.md` for the full narrative.

**Playbook when smoke fails a CORE test:**

1. Confirm the failure on a clean deploy (guest disk state can
   masquerade as a code bug). Delete everything under `T:` and
   the target file under `DH1:lib/`, re-deploy, re-run smoke.

2. If still failing, bisect **shim vs interpreter vs stdlib**:
   - swap `Python/fileutils.c` for stock CPython 3.12.7 → rebuild
   - if fixed → suspect `_Py_normpath_and_size` / fileutils edits
   - if still broken → suspect `amiga_shim.c` or a stdlib
     `.py` shim under `Python-3.12.7/Lib/`

3. If bisected to shim, add a `printf` at the top of
   `amiga_open`/`amiga_fopen` logging `path, tp, fd` — deploy
   the debug build, run `python-os4 DH1:smoke.py`, read
   `T:amiga_shim.log` to see which call fails.

4. Fix, re-run smoke, PR.

## When a change breaks EMBED

Almost always: a C compilation change (Bill's territory —
build flags, shim signatures, `_amigamodule.c`, or the
`-include amiga_shim.h` `#define` collisions). Test with a
minimal C program that links against `libpython.a` and calls
`Py_Initialize()`. If that fails, GemRB will fail too.

## When a change breaks INTEGRATION only

Usually pip / ssl / socket — my territory. See
`docs/PIP.md` for pip specifics. For ssl, run
`pydiags ssl` on the guest — it's a purpose-built probe.

## Style notes

- **AmigaDOS `;` is a comment marker.** Quote PYTHONPATH values
  with multiple entries: `"DH1:lib;DH1:pytests"`.
- **The clock is wall-local, not UTC.** TLS cert validity and
  git commit timestamps will look wrong if the guest clock is off.
- Never use `_>_file` (stdin redirect) in AmigaDOS shell — it
  doesn't work. Use `type file | prog`.
- For iteration testing, **xdftool direct-write beats the
  serial bridge** for anything > 100 KB. See `PIP_STATUS.md`
  for the exact recipe.

## Repo state / commit hygiene

- Every commit should leave `main` in a state where the offline
  test suite passes. If a CORE test fails, either fix in the
  same commit or hold the PR.
- Long-running notes for future sessions: `PIP_STATUS.md`,
  `MERGE_REGRESSION.md`, `PIP_NEXT_STEPS.md` (before it was
  renamed). New session-handoff docs should follow the same
  pattern: what works, what's blocked, exact repro commands.
- Task tracking during development: use whatever fits, but
  never merge a PR without running the pre-PR checklist above.
