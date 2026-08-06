# amiga.pip — status

Last update: 2026-08-05 evening.

## TL;DR

`amiga.pip.install(name)` works **end-to-end on-guest**. Verified
by installing `chardet-7.5.1` into `DH1:lib/chardet/` with a
mocked HTTPS transport (real PyPI JSON + real wheel bytes,
served locally to avoid needing a working NIC on the guest).
Package landed on disk with the correct 15-file layout and
`chardet-7.5.1.dist-info/` metadata directory.

## Confirmed on-guest

1. `import amiga.pip` — loads (deferred hashlib import prevents
   AmiSSL blocking).
2. `amiga.pip.install("chardet", target="DH1:lib")`
   → parses 416 KB PyPI JSON
   → resolver picks `chardet-7.5.1-py3-none-any.whl` from all
     available files
   → downloads (via mocked amiga.https that returned a 655 KB
     wheel byte-for-byte from `files.pythonhosted.org`)
   → SHA-256 verify passes (`ba7e9b6c15b4fcdf…`)
   → `install_wheel()` extracts into `DH1:lib`
   → returns `InstalledPackage(name='chardet', version='7.5.1',
     dist_info_dir='DH1:lib/chardet-7.5.1.dist-info')`
3. **On-disk verify** (walk `DH1:lib/chardet/`): 15 files
   including `__init__.py`, `detector.py`, `enums.py`,
   `models/`, `_utils.py`, `_version.py`, etc.
4. **`chardet-7.5.1.dist-info/`** — created with METADATA
   present (readable by `list_installed()`).

## What DOESN'T work (yet)

- **`import chardet` at runtime** — chardet 7.x does
  `import importlib.resources` in `chardet/models/__init__.py`.
  `importlib.resources` was purged from this Python's stdlib
  during `package-stdlib.sh` (see `rm -rf ... ensurepip ...`).
  This isn't a pip issue — the package installed correctly. To
  fix: either restore `importlib.resources` in the stdlib zip,
  or install an older `chardet` (5.x) that doesn't need it.

- **Live HTTPS to pypi.org from guest** — the QEMU guest has
  no default route configured. `ping 192.168.100.2` (gateway)
  works, but `ping 8.8.8.8` gets `bsdsocket error -1`. Roadshow
  is present but `AddInet` isn't (different network stack).
  To restore, either add:
  ```
  Run AddNetInterface virte1000
  Wait 3
  ; needs whatever OS4-native route helper exists here
  ```
  to `S:User-Startup`, or figure out which network tool this
  particular OS4 install uses.

  For the pip flow, this only matters when hitting real PyPI —
  the install logic works given a working HTTPS transport
  (which we mocked above).

## Files

Deployed to `DH1:lib/amiga/pip/` (not `DH1:pytests/…` — the
existing `DH1:lib/amiga/` package takes precedence in
Python's package resolution):

```
DH1:lib/amiga/pip/__init__.py    12 KB   install() + install_wheel() + download_wheel()
DH1:lib/amiga/pip/resolver.py    11 KB   PyPI JSON → wheel URL, PEP 440 version compare
DH1:lib/amiga/pip/cache.py        2 KB   content-addressed cache, SHA-256 verify
DH1:lib/amiga/pip/__main__.py     2 KB   CLI: `python -m amiga.pip {install|list|uninstall}`
```

Launcher script for muscle-memory `pip install foo` (also
deployed):

```
DH1:scripts/pip                          `execute DH1:scripts/pip install six`
```

Test fixtures (for offline verification):

```
DH1:chardet.json  DH1:chardet.whl     — pre-downloaded PyPI JSON + wheel
DH1:six.json      DH1:six.whl         — for the simpler smoke test
DH1:mock_install.py                    — install-with-mocked-HTTPS probe
DH1:verify.py                          — chardet-on-disk verifier
DH1:run_pip.py                         — live-network install probe (needs NIC)
```

## Offline tests

40 tests, all passing on host Python:

```
tests/test_pip_resolver.py  24   version parsing, wheel filter, PyPI JSON resolve
tests/test_pip_cache.py      6   sha256, verify, path handling
tests/test_pip_install.py   10   full mocked install flow, dep walking, dedup
```

Run: `python3 tests/test_pip_resolver.py` (etc.)

## Repro (from a fresh session)

```bash
# 1. offline sanity
cd ~/code/claude_world/python-amigaos4
for t in tests/test_pip_*.py; do python3 $t; done   # all should say OK

# 2. deploy fresh pip package to guest disk (QEMU stopped)
pkill -9 -f qemu-system-ppc; sleep 2
for f in __init__.py resolver.py cache.py __main__.py; do
    xdftool ~/AmigaOS4/amigaos4-dev.hdf write \
        amiga_bindings/amiga/pip/$f lib/amiga/pip/$f
done

# 3. deploy test fixtures + probe script
xdftool ~/AmigaOS4/amigaos4-dev.hdf write /tmp/fixtures/chardet.json chardet.json
xdftool ~/AmigaOS4/amigaos4-dev.hdf write /tmp/fixtures/chardet.whl chardet.whl
xdftool ~/AmigaOS4/amigaos4-dev.hdf write /tmp/mock_install.py mock_install.py
xdftool ~/AmigaOS4/amigaos4-dev.hdf write /tmp/mock_run.script mock_run.script

# 4. boot + run
~/code/claude_world/amiga_mcp/scripts/start-qemu-os4.sh --gdb --gdb-port 4433 &
# wait for tick>=8 silent<3 then:
curl -s -X POST http://localhost:3000/api/launch \
     -H 'Content-Type: application/json' \
     -d '{"command":"execute DH1:mock_run.script"}'

# 5. read log
curl -s "http://localhost:3000/api/file?path=T:mockrun.log&offset=0&size=8192" | \
    python3 -c 'import sys,json,binascii;h=json.load(sys.stdin).get("hexData","");\
                print(binascii.unhexlify(h).decode("latin-1",errors="replace"))'
```

Expected tail: `=== ALL OK ===`.

## Multi-dep test (requests)

Not attempted yet. Would exercise diamond deps
(certifi/idna/urllib3/charset-normalizer). Same recipe: pre-fetch
the JSON+wheel for each, mock amiga.https to serve them by URL.

## Live network path (real pip install)

Once the guest NIC is properly configured with a default route
+ DNS, `run_pip.py` on `DH1:` (already deployed) does the same
full flow but hits real pypi.org via the openssl s_client
shell-out. It got to step 6 in the last attempt before failing
at "No route to host" — proves the code path is right, just
the transport isn't up.

Fix path: get the OS4-native equivalent of Roadshow's
`AddInet Route DEFAULT GATEWAY 192.168.100.2` working.
