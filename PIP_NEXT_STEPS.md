# amiga.pip — status & next steps

Last update: 2026-08-05, HEAD `8682139`.

## What's done

`amiga.pip` now has a full `install(name)` flow with dep resolution:

| Piece | Where | State |
| ----- | ----- | ----- |
| `install(name, target=DH1:lib)` — resolve + download + install + walk deps | `amiga_bindings/amiga/pip/__init__.py` | Written, 40 offline tests pass |
| PyPI JSON resolver + PEP 440 version compare + PEP 427 wheel filter + PEP 508 requirement splitter | `amiga_bindings/amiga/pip/resolver.py` | Written, 24 tests |
| Content-addressed wheel cache + SHA-256 verify | `amiga_bindings/amiga/pip/cache.py` | Written, 6 tests |
| CLI: `python -m amiga.pip {install\|list\|uninstall}` | `amiga_bindings/amiga/pip/__main__.py` | Written |
| AmigaDOS launcher: `execute DH1:scripts/pip install …` | `scripts/launchers/pip` | Written, deployed |
| `download_wheel(url, dst)` — HTTPS via `amiga.https`, redirects | `amiga_bindings/amiga/pip/__init__.py` | Written |

Live spot-check against real PyPI JSON confirms the resolver picks
the right wheel for chardet / idna / requests / urllib3 with sensible
dep lists (extras/platform markers correctly flagged optional).

## On-guest smoke test — NOT YET COMPLETED

Deploy path is proven (xdftool direct-write into
`amigaos4-dev.hdf`), files present at:

    DH1:pytests/amiga_bindings/amiga/pip/__init__.py
    DH1:pytests/amiga_bindings/amiga/pip/resolver.py
    DH1:pytests/amiga_bindings/amiga/pip/cache.py
    DH1:pytests/amiga_bindings/amiga/pip/__main__.py
    DH1:scripts/pip                       (launcher)

Environment vars must have `PYTHONPATH` quoted because AmigaDOS
treats bare `;` as a comment marker:

    setenv PYTHONHOME DH1:
    setenv PYTHONPATH "DH1:lib;DH1:pytests/amiga_bindings"
    DH1:python-os4 -m amiga.pip install chardet --target DH1:lib

**Confirmed working on-guest**:
- `python-os4 -V` prints `Python 3.12.7`
- `python-os4 -c "print('hello')"` prints `hello` (takes ~10s to run cold)
- With PYTHONPATH set correctly, `sys.path` includes
  `DH1:pytests/amiga_bindings` (verified via probe script)

**What failed on-guest**:
- `python-os4 T:imp_probe.py` — the file at `T:` path apparently
  couldn't be opened / Python hung before executing the script body.
  Moving the same file to `DH1:` fixed it (probe wrote its startup
  banner to `T:imp.log`).
- `import amiga.pip` from that probe — the log stopped after
  `path:` line and before printing whether import succeeded, then
  the bridge went wedged (heartbeats fine, launch handler stuck).
  Never got to see the outcome of the amiga.pip import.

## Next session's diagnostic plan

1. **Fresh QEMU + devbench restart** (`pkill -9 -f qemu-system-ppc;
   pkill -9 -f amiga_devbench; sleep 3; start both`).

2. **Repeat the step-by-step import probe** (already sitting at
   `DH1:imp_probe2.py` on-guest):

        execute T:py_imp5.script    # → wait, then read T:imp.log

   The probe imports `amiga`, then `amiga.pip`, then
   `amiga.pip.resolver`, then `amiga.pip.cache`, logging each
   step to `T:imp.log`. Whichever step hangs is the culprit.

3. **Suspected root cause** — `amiga/__init__.py` is clean (no
   side-effecty imports). `amiga.pip.__init__` only imports stdlib.
   But `amiga.pip.resolver` uses `re` and `collections.namedtuple`.
   And `amiga.pip.cache` uses `hashlib`. If `hashlib` on OS4 forces
   AmiSSL to open at import time (rather than lazily as advertised
   in the port README), that's a 5-15 second stall while
   `amissl.library` loads. Likely explanation for perceived
   "hang" — Python is slow but alive.

   Workaround if confirmed: defer the `import hashlib` in cache.py
   from module level to inside `sha256_file()`.

4. **Once import works, try the install**:

        execute DH1:scripts/pip install chardet

   Expected outcome: `installed: chardet <version>` on stdout,
   files appear under `DH1:lib/chardet/`.

5. **HTTPS chain-of-custody check**: before the install actually
   tries to download a wheel, confirm `amiga.https.get("https://pypi.org/pypi/chardet/json")`
   returns status 200 with a JSON body. If it fails at the AmiSSL
   layer (cert bundle, timezone/UTC clock skew), the install
   error will be misleading. The `pydiags ssl` subcommand
   probably already exercises this — run it first.

## Reproduction quickstart

Everything committed on `main` at `8682139`. To pick up:

    cd ~/code/claude_world/python-amigaos4

    # 1. offline tests (should all pass)
    python3 tests/test_pip_resolver.py
    python3 tests/test_pip_cache.py
    python3 tests/test_pip_install.py

    # 2. deploy via xdftool (QEMU must be stopped)
    pkill -9 -f qemu-system-ppc; sleep 2
    for f in amiga_bindings/amiga/pip/__init__.py \
             amiga_bindings/amiga/pip/resolver.py \
             amiga_bindings/amiga/pip/cache.py \
             amiga_bindings/amiga/pip/__main__.py; do
        n=$(basename $f)
        xdftool ~/AmigaOS4/amigaos4-dev.hdf delete pytests/amiga_bindings/amiga/pip/$n
        xdftool ~/AmigaOS4/amigaos4-dev.hdf write $f pytests/amiga_bindings/amiga/pip/$n
    done

    # 3. boot + wait
    ~/code/claude_world/amiga_mcp/scripts/start-qemu-os4.sh --gdb --gdb-port 4433 &
    # wait for heartbeat tick>=6, silent<3

    # 4. try the install
    curl -s -X POST http://localhost:3000/api/launch \
         -H 'Content-Type: application/json' \
         -d '{"command":"execute DH1:scripts/pip install chardet"}'

    # 5. read result
    curl -s "http://localhost:3000/api/file?path=T:pip.log&offset=0&size=8192" | \
        python3 -c 'import sys,json,binascii;h=json.load(sys.stdin).get("hexData","");\
                    print(binascii.unhexlify(h).decode("latin-1",errors="replace"))'

## Known caveats

- `amiga.https` uses shell-out to `openssl s_client` — a whole
  Amiga process spawn per HTTPS request. Fine for a handful of
  wheel downloads. Would be slow if pulling dozens of deps.
  Real fix is the "task #94" `_ssl/_socket` fd interop bug from
  the port README.
- The Amiga clock must be within 24h of real UTC for cert
  validation to pass. If installs fail with cryptic errors,
  `date` on the guest and reset if needed.
- pip's own vendored `packaging` is available in
  `DH1:lib/ensurepip/_bundled/pip-24.2-py3-none-any.whl` (as a
  wheel-on-disk), but we deliberately do not depend on it —
  our resolver has its own PEP 440 version comparator so a
  bootstrap chicken-egg is impossible.
- We install to `DH1:lib` by default which is on the default
  PYTHONPATH. Real pip installs to `site-packages/`. If we ever
  add a `--user` mode, `System/python3/lib/site-packages/`
  (from the release-installer commit) is where it should go.
