# Using pip on AmigaOS 4

`amiga.pip` is a **subprocess-free wheel installer** for the OS4
Python port. It replaces `python -m pip`, which won't run on
newlib (no `fork()`), with a small in-process installer that:

- fetches package metadata from PyPI over HTTPS (via `amiga.https`)
- resolves + downloads a **`py3-none-any` wheel** for the latest
  release
- verifies its SHA-256 against the PyPI digest
- extracts into `python3:lib/` (or wherever you point it)
- walks `Requires-Dist` and installs non-optional dependencies

**Constraints, up front:**

- **Pure-Python wheels only.** Anything with a compiled `.so`
  (numpy, cryptography, Pillow) is rejected — we have no C build
  toolchain on the guest.
- **AmiSSL must be installed** for HTTPS to PyPI to work. See
  [INSTALL.md](INSTALL.md).
- **Guest clock must be within 24h of real UTC.** TLS cert
  validation fails silently otherwise.
- **Network must be up.** `ping 8.8.8.8` should succeed before
  you try to install anything.

## Prerequisites (one-time)

Add these to `S:User-Startup` (or run once per boot):

```
assign python3: DH1:
setenv PYTHONHOME python3:
setenv PYTHONPATH "python3:lib"
```

**Note the quotes on PYTHONPATH.** AmigaDOS treats a bare `;` as
a comment marker, so if you ever need multiple entries
(`"python3:lib;python3:extras"`), the whole value must be quoted
or everything after the first `;` disappears silently.

Sanity check:

```
python3 -V
```

Expected: `Python 3.12.7`.

## Quick install a package

Three equivalent ways to install `six` (a pure-Python compat
library, one of the smallest useful packages on PyPI):

### 1. From the shell

```
execute python3:scripts/pip install six
```

### 2. Direct interpreter

```
python3 -m amiga.pip install six
```

### 3. Programmatically

```python
import amiga.pip
amiga.pip.install("six")
```

All three do the same thing: fetch `https://pypi.org/pypi/six/json`,
pick the highest stable `py3-none-any` wheel, download from
`files.pythonhosted.org`, SHA-256 verify, extract into
`python3:lib/six/`.

Expected output (`pip install six`):

```
[amiga.pip] resolving six...
[amiga.pip] downloading six 1.17.0 (https://files.pythonhosted.org/.../six-1.17.0-py2.py3-none-any.whl)
installed: six 1.17.0
```

Verify it works:

```
python3 -c "import six; print(six.__version__)"
```

Expected: `1.17.0`.

## Listing installed packages

```
execute python3:scripts/pip list
```

Or:

```python
import amiga.pip
for pkg in amiga.pip.list_installed():
    print(pkg.name, pkg.version)
```

Output looks like:

```
chardet                        5.2.0
idna                           3.6
requests                       2.31.0
six                            1.17.0
urllib3                        2.1.0
```

The list is built by walking `*.dist-info` directories under
`python3:lib/` — there's no separate database.

## Uninstalling

```
execute python3:scripts/pip uninstall six
```

Reads the `RECORD` file inside the package's `.dist-info` dir
and removes each listed file. Best-effort — leaves empty parent
directories behind.

## Working with dependencies

`install()` recursively resolves `Requires-Dist` entries. Extras
(`something ; extra == 'foo'`) and platform-specific markers
(`; sys_platform == "win32"`) are skipped automatically.

Example — install `requests`, which pulls in
`charset-normalizer + idna + urllib3 + certifi`:

```
execute python3:scripts/pip install requests
```

Output:

```
[amiga.pip] resolving requests...
[amiga.pip] downloading requests 2.31.0 (...requests-2.31.0-py3-none-any.whl)
[amiga.pip] resolving charset-normalizer...
[amiga.pip] downloading charset-normalizer 3.3.2 (...charset_normalizer-3.3.2-py3-none-any.whl)
[amiga.pip] resolving idna...
[amiga.pip] downloading idna 3.6 (...idna-3.6-py3-none-any.whl)
[amiga.pip] resolving urllib3...
[amiga.pip] downloading urllib3 2.1.0 (...urllib3-2.1.0-py3-none-any.whl)
[amiga.pip] resolving certifi...
[amiga.pip] downloading certifi 2024.2.2 (...certifi-2024.2.2-py3-none-any.whl)
installed: requests 2.31.0
installed: charset_normalizer 3.3.2
installed: idna 3.6
installed: urllib3 2.1.0
installed: certifi 2024.2.2
```

`requests.get()` should now work over plain HTTP (HTTPS still
goes through the `amiga.https` shell-out — see below).

## Examples worth trying

All of these are pure-Python and have small dep trees.

### `python-dateutil` — richer datetime handling

```
execute python3:scripts/pip install python-dateutil
```

```python
from dateutil.parser import parse
print(parse("Tue, 05 Aug 2026 14:30 UTC"))
# 2026-08-05 14:30:00+00:00
```

### `packaging` — PEP 440 version compare, PEP 508 markers

```
execute python3:scripts/pip install packaging
```

```python
from packaging.version import Version
print(sorted([Version(v) for v in ["1.0.0", "1.10.0", "1.2.0"]]))
# [<Version('1.0.0')>, <Version('1.2.0')>, <Version('1.10.0')>]
```

### `pyyaml`

**Doesn't work** — pyyaml wheels contain a compiled C extension
(`_yaml.so`) for speed. There's a pure-Python fallback, but the
wheel that ships to PyPI includes both, and `amiga.pip` refuses
it because of the `.so`. Workaround: download the sdist manually
and extract just `yaml/` into `python3:lib/`.

### `pytoml` / `tomli` — TOML parsing

```
execute python3:scripts/pip install tomli
```

```python
import tomli
print(tomli.loads('key = "value"\n[section]\nn = 42\n'))
# {'key': 'value', 'section': {'n': 42}}
```

### `markdown` — Markdown to HTML

```
execute python3:scripts/pip install markdown
```

```python
import markdown
print(markdown.markdown("# Hello\n\nThis is **Markdown** on *Amiga*."))
# <h1>Hello</h1>
# <p>This is <strong>Markdown</strong> on <em>Amiga</em>.</p>
```

## Using a custom package index

By default `amiga.pip` fetches from **pypi.org**. You can point
it at a mirror, a test index, or an internal server that speaks
the same Warehouse JSON API (`{base}/{name}/json`).

Common cases:

- **Test PyPI** for pre-release packages you're validating
- **Local devpi** for offline development or a curated mirror
- **Internal corporate index** for private packages
- **GitHub Releases / S3 static mirror** for a small curated
  wheel set (useful when your Amiga has no working DNS)

### From the shell

```
execute python3:scripts/pip install mypkg --index-url https://test.pypi.org/pypi/
```

Fall back to PyPI if a package isn't in the primary index:

```
execute python3:scripts/pip install mypkg
  --index-url        https://internal.example.com/pypi/
  --extra-index-url  https://pypi.org/pypi/
```

`--extra-index-url` may be repeated. Indexes are tried in order;
the first one to return the package wins. This mirrors
stock pip's semantics.

### From Python

```python
import amiga.pip

# Only Test PyPI
amiga.pip.install("mypkg",
    index_url="https://test.pypi.org/pypi/")

# Internal first, PyPI as fallback
amiga.pip.install("acme-widget",
    index_url="https://pkg.corp.example.com/pypi/",
    extra_index_urls=("https://pypi.org/pypi/",))
```

### Setting a global default

If you always want the same index (e.g. a local mirror is
always faster than PyPI from Amiga's slow HTTPS shell-out), set
the module-level default at boot:

```python
import amiga.pip
amiga.pip.DEFAULT_INDEX_URL = "https://mirror.local/pypi/"
```

Or add to `S:User-Startup` via a tiny bootstrap script:

```
setenv PYTHONHOME python3:
setenv PYTHONPATH "python3:lib"
python3 -c "import amiga.pip; amiga.pip.DEFAULT_INDEX_URL='https://mirror.local/pypi/'; print('using mirror')"
```

### Example: Test PyPI end-to-end

Test PyPI hosts alpha/beta releases that maintainers upload
before promoting to real PyPI. It's a good target for verifying
your index-URL setup because it exists and uses the same
JSON-API format.

```
execute python3:scripts/pip install six
  --index-url https://test.pypi.org/pypi/
  --pre
```

The `--pre` flag lets us pick pre-release versions (test.pypi
frequently only has those).

### Format requirements

The custom index must speak the **Warehouse `/pypi/{name}/json`
API** — the same shape pypi.org serves. That includes:

- pypi.org and test.pypi.org (obvious)
- **devpi** with the `devpi-server` default config
- **pypiserver** with `--pypi-package-listing` enabled
- Anything that reverse-proxies to a real PyPI

It does **not** yet include:

- Plain PEP 503 "simple" index (HTML file listing) — devpi's
  `/root/pypi/+simple/` for example
- Artifactory's `/api/pypi/pypi/simple/`
- Bare directories of wheels served by nginx

Support for the simple API is on the roadmap.

## Advanced: version pinning

```python
import amiga.pip
# Install a specific older version (e.g. chardet 5.x, which doesn't
# depend on importlib.resources).
from amiga.pip.resolver import resolve_from_json
from amiga import https as _h
import json
data = json.loads(_h.get("https://pypi.org/pypi/chardet/json")[2])
release = resolve_from_json(data, prefer_version="5.2.0")
# manual install of that specific wheel:
amiga.pip.download_wheel(release.wheel_url, f"T:{release.name}.whl")
amiga.pip.install_wheel(f"T:{release.name}.whl", target="python3:lib")
```

The high-level `install(name)` currently only picks the highest
stable version. Version specifiers (`chardet<6`, `six>=1.10`) are
planned but not yet plumbed through the CLI.

## Cache management

Downloaded wheels are cached at `T:pip-cache/` (RAM disk — lost
on reboot). To move the cache to persistent storage:

```python
import amiga.pip
amiga.pip.install("six", cache_dir="python3:pip-cache")
```

Or set it globally via a helper:

```python
import amiga.pip.cache
amiga.pip.cache.DEFAULT_CACHE_DIR = "python3:pip-cache"
amiga.pip.install("requests")
```

Cache entries are content-addressed by wheel filename. Deleting a
file forces a re-download on next install.

## Local wheel installation (offline)

If you already have a wheel file on disk (e.g. downloaded from a
different machine and copied via `xdftool`), skip the network
altogether:

```python
from amiga.pip import install_wheel
install_wheel("DH1:downloads/six-1.17.0-py2.py3-none-any.whl",
              target="python3:lib")
```

Or from the shell — this works without any network at all, useful
for airgapped installs:

```
python3 -c "from amiga.pip import install_wheel; install_wheel('DH1:downloads/six-1.17.0-py2.py3-none-any.whl')"
```

## Known limits

- **No `python -m pip install`** — real pip needs `fork()` for
  its subprocess-based build backends. Use `python3 -m amiga.pip
  install` instead.
- **Compiled wheels rejected** — `.so`, `.pyd`, `.dylib` in the
  wheel triggers a `WheelError`. No workaround without a compiler
  on the guest.
- **HTTPS is slow** — every HTTPS request forks an `openssl
  s_client` subprocess (task #94 workaround). A single package
  install takes 5–30 seconds. A big dep tree can take minutes.
- **`installed` list uses the on-disk filename convention** —
  `charset-normalizer` shows up as `charset_normalizer` in the
  list because that's how the wheel's `.dist-info` dir names it.
  Both `pip install charset-normalizer` and
  `pip install charset_normalizer` work — they're canonicalised
  internally per PEP 503.
- **Extras are silently skipped** — `pip install requests[socks]`
  installs the same wheels as `pip install requests` (no
  `[socks]` support). File an issue if you need extras honored.
- **No version specifiers in the CLI yet** — always installs the
  latest stable. Use the programmatic path shown above for
  pinning.
- **Custom index must speak the Warehouse JSON API** — plain
  PEP 503 "simple" indexes (HTML listing) don't work yet. See
  "Format requirements" under the custom-index section.

## When things go wrong

**"No route to host"** when installing:
   guest network isn't set up. Confirm `ping 8.8.8.8` works
   before invoking pip. If it doesn't, fix your network config
   (Roadshow `AddInet Route`, or your OS4 build's equivalent).

**"certificate has expired"** or TLS handshake failures:
   guest clock is off by more than a day. Set with:

   ```
   date DD-MMM-YY HH:MM:SS
   ```

   (Enter the value as `real_UTC - your_timezone_offset` — the
   Amiga clock is stored as wall-local, and OS4's newlib
   `time.gmtime()` re-adds the TZ offset.)

**"WheelError: platform-specific wheel not supported"**:
   PyPI doesn't have a `py3-none-any` wheel for that package. You
   can't install it without a compiler. Look for a pure-Python
   fallback (e.g. `cryptography-pyopenssl-fallback`,
   `pycryptodome` for some crypto uses).

**"WheelError: SHA256 mismatch"**:
   corrupted download. Delete the cached wheel (`delete
   T:pip-cache/foo-*.whl`) and re-run.

**Package installs but import fails with `ModuleNotFoundError:
No module named 'importlib.resources'`**:
   this Python's stdlib has been slimmed and doesn't include
   `importlib.resources` (or `importlib.metadata`). Some modern
   packages (chardet 7.x, click 8.x) need it. Workarounds:
   pin to an older version of the package that doesn't require
   it, or add the missing stdlib module back to `python3:lib/`
   from a full CPython 3.12 install.

## What's next

- Version specifier syntax in the CLI (`pip install six>=1.15`)
- `--target` flag support in the shell launcher
- PEP 503 simple-index parser (HTML listing) — lets you point
  at devpi's `/+simple/`, Artifactory's `/simple/`, or a plain
  directory of wheels served over HTTP
- Optional AmiSSL-free HTTP-only mode (for pypi mirrors that
  serve HTTP — mostly for CI/testing)
- A curated wheel mirror on GitHub Releases for the "just works"
  path when live PyPI is unreachable

## Related

- [INSTALL.md](INSTALL.md) — installing AmiSSL (required for
  HTTPS)
- [RUNNING.md](RUNNING.md) — general Python setup on OS4
- `PIP_STATUS.md` at repo root — implementation status +
  developer testing recipes
