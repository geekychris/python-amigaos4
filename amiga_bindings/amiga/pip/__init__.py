"""
amiga.pip — subprocess-free wheel installer for the OS4 Python port.

Real pip needs fork+exec (via subprocess) to run isolated build backends
and hash verification helpers.  Newlib on OS4 has no fork(), so the
`pip install X` command line never gets past its startup.

This module offers a working subset:

  - install(name, target=DH1:lib)  — full flow: resolve name against
      PyPI JSON, follow dependencies, download each wheel over HTTPS
      via amiga.https, verify SHA256, extract into `target`.
      Pure-Python + non-optional deps only.

  - install_wheel(path_to_wheel, target=DH1:lib)  — extract a single
      already-downloaded `*-py3-none-any.whl` into `target`. Refuses
      compiled-C wheels.

  - download_wheel(url, dst) — HTTPS via amiga.https, HTTP via raw
      socket. Follows redirects.

  - list_installed(target) / uninstall(name, target) — same as
      before; walk *.dist-info dirs.

Real pip is still shipped in DH1:lib/ensurepip/_bundled/ (the wheel).
`python -m pip` will fail at any subprocess boundary, but you can
still `import pip; pip.__version__` for library-level use.
"""
import json as _json
import os
import sys
import zipfile
from collections import namedtuple
# hashlib intentionally NOT imported at module level — see cache.py.

InstalledPackage = namedtuple(
    "InstalledPackage", "name version dist_info_dir"
)


class WheelError(Exception):
    """Raised on invalid or unsupported wheel files."""


# ---------------------------------------------------------------------------
# Wheel install / uninstall
# ---------------------------------------------------------------------------

def install_wheel(wheel_path, target=None, verbose=False):
    """Extract a `*-py3-none-any.whl` into `target` (defaults to sys.path[0]
    if it's a directory, else `DH1:lib`).

    Returns the installed InstalledPackage record.
    Raises WheelError if the wheel is platform-specific (has *.so, *.pyd,
    or a non-`any` platform tag).
    """
    if target is None:
        target = "DH1:lib"

    fname = os.path.basename(wheel_path)
    if not fname.endswith(".whl"):
        raise WheelError(f"not a wheel: {wheel_path}")
    # Wheel filename convention: {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
    stem = fname[:-4]
    parts = stem.split("-")
    if len(parts) < 5:
        raise WheelError(f"unparseable wheel name: {fname}")
    name, version = parts[0], parts[1]
    platform_tag = parts[-1]
    if platform_tag != "any":
        raise WheelError(
            f"platform-specific wheel not supported on Amiga: {platform_tag}"
        )

    with zipfile.ZipFile(wheel_path) as z:
        entries = z.namelist()
        for e in entries:
            if e.endswith((".so", ".pyd", ".dylib")):
                raise WheelError(f"compiled extension in wheel: {e}")
        dist_info = None
        for e in entries:
            if e.endswith(".dist-info/METADATA"):
                dist_info = e.split(".dist-info/", 1)[0] + ".dist-info"
                break
        if verbose:
            print(f"[amiga.pip] installing {name} {version} ({len(entries)} entries)")
        for e in entries:
            if e.endswith("/"):
                continue
            # Skip entry_points scripts installer needs; we don't have them
            if e.endswith(".dist-info/RECORD") or ".data/scripts/" in e:
                continue
            z.extract(e, target)

    return InstalledPackage(name=name, version=version,
                            dist_info_dir=os.path.join(target, dist_info)
                                          if dist_info else "")


def list_installed(target=None):
    """Enumerate *.dist-info dirs under target — that's a proxy for
    'installed packages' since we don't maintain a real database."""
    if target is None:
        target = "DH1:lib"
    out = []
    try:
        for name in os.listdir(target):
            if name.endswith(".dist-info"):
                pkg = name[:-len(".dist-info")]
                bits = pkg.rsplit("-", 1)
                if len(bits) == 2:
                    out.append(InstalledPackage(
                        name=bits[0], version=bits[1],
                        dist_info_dir=os.path.join(target, name)))
    except OSError:
        pass
    return out


def uninstall(name, target=None):
    """Remove a package installed by install_wheel.  Best-effort: reads
    the RECORD in the dist-info dir if present, else scans."""
    if target is None:
        target = "DH1:lib"
    import shutil
    for pkg in list_installed(target):
        if pkg.name.lower() == name.lower():
            record = os.path.join(pkg.dist_info_dir, "RECORD")
            if os.path.exists(record):
                with open(record) as f:
                    for line in f:
                        path = line.split(",", 1)[0].strip()
                        full = os.path.join(target, path)
                        try:
                            os.remove(full)
                        except OSError:
                            pass
            try:
                shutil.rmtree(pkg.dist_info_dir)
            except OSError:
                pass
            # Also try nuking the top-level package dir
            for candidate in (pkg.name, pkg.name.replace("-", "_")):
                d = os.path.join(target, candidate)
                if os.path.isdir(d):
                    try:
                        shutil.rmtree(d)
                    except OSError:
                        pass
            return True
    return False


# ---------------------------------------------------------------------------
# Wheel download (HTTP only — no SSL yet)
# ---------------------------------------------------------------------------

def download_wheel(url, dst):
    """Fetch a wheel from an http:// or https:// URL, saving to `dst`.

    HTTPS is routed through amiga.https (openssl s_client shell-out —
    task #94 workaround). HTTP uses a raw socket so we don't depend
    on urllib being present in the on-guest install.
    """
    if url.startswith("https://"):
        return _download_https(url, dst)
    if url.startswith("http://"):
        return _download_http(url, dst)
    raise WheelError(f"unsupported URL scheme: {url}")


def _download_https(url, dst, follow_redirects=5):
    """HTTPS download via amiga.https. Follows redirects up to N hops
    since PyPI's wheel URLs often redirect from pypi.org to
    files.pythonhosted.org."""
    from amiga import https as _https  # deferred: keep pip importable off-target
    while True:
        status, headers, body = _https.get(url)
        if status in (301, 302, 303, 307, 308) and follow_redirects > 0:
            loc = headers.get("location")
            if not loc:
                raise WheelError(f"redirect {status} without Location")
            url = loc
            follow_redirects -= 1
            continue
        if status != 200:
            raise WheelError(f"HTTPS {status} for {url}")
        with open(dst, "wb") as f:
            f.write(body)
        return dst


PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"


def _fetch_pypi_json(name):
    """Fetch and parse the PyPI JSON metadata for `name`."""
    from amiga import https as _https
    url = PYPI_JSON_URL.format(name=name)
    status, headers, body = _https.get(url)
    if status == 404:
        raise WheelError(f"package not found on PyPI: {name}")
    if status != 200:
        raise WheelError(f"PyPI JSON {name} returned HTTP {status}")
    try:
        return _json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        raise WheelError(f"malformed JSON from PyPI for {name}: {e}") from e


def _canonical_name(name):
    """PEP 503 normalisation — lowercase and squash runs of ._- to '-'.
    Two packages are considered the same iff their canonical names match."""
    import re
    return re.sub(r"[-_.]+", "-", name).lower()


def install(name, target=None, cache_dir=None, verbose=True,
            allow_pre=False, _visited=None):
    """Install `name` and its dependencies (pure-Python wheels only).

    Recursion order: resolve name → download wheel → install → read
    METADATA → for each Requires-Dist that isn't optional (extras /
    unmet marker), recurse.

    Returns a list of InstalledPackage records for everything newly
    installed this call (already-installed deps aren't listed).
    """
    from amiga.pip import resolver as _r
    from amiga.pip import cache as _c

    if target is None:
        target = "DH1:lib"
    if cache_dir is None:
        cache_dir = _c.DEFAULT_CACHE_DIR
    if _visited is None:
        _visited = set()

    canon = _canonical_name(name)
    if canon in _visited:
        return []
    _visited.add(canon)

    # Skip anything already installed at target.
    for pkg in list_installed(target):
        if _canonical_name(pkg.name) == canon:
            if verbose:
                print(f"[amiga.pip] {name} already installed as "
                      f"{pkg.name} {pkg.version}")
            return []

    if verbose:
        print(f"[amiga.pip] resolving {name}...")
    data = _fetch_pypi_json(name)
    rel = _r.resolve_from_json(data, allow_pre=allow_pre)

    # If the JSON's top-level info was for a different version than
    # what we picked, requires_dist may be missing. Refetch the
    # per-version JSON for authoritative deps.
    reqs = rel.requires_dist
    top_info_version = (data.get("info") or {}).get("version")
    if not reqs and top_info_version != rel.version:
        try:
            data2 = _fetch_pypi_json(f"{name}/{rel.version}")
        except WheelError:
            data2 = None
        if data2:
            info = data2.get("info") or {}
            reqs = tuple(info.get("requires_dist") or ())

    # Download (or use cache) + verify.
    dst = _c.cache_path_for(rel.wheel_url, cache_dir=cache_dir)
    if _c.verify(dst, rel.wheel_sha256):
        if verbose:
            print(f"[amiga.pip] using cached {os.path.basename(dst)}")
    else:
        if verbose:
            print(f"[amiga.pip] downloading {rel.name} {rel.version} "
                  f"({rel.wheel_url})")
        download_wheel(rel.wheel_url, dst)
        if rel.wheel_sha256 and not _c.verify(dst, rel.wheel_sha256):
            try:
                os.remove(dst)
            except OSError:
                pass
            raise WheelError(
                f"SHA256 mismatch for {rel.name} {rel.version}")

    # Install.
    installed = install_wheel(dst, target=target, verbose=verbose)
    installed_list = [installed]

    # Walk deps.
    for req in reqs:
        req_name, _spec, marker = _r.parse_requirement(req)
        if not req_name:
            continue
        if _r.requirement_is_optional(marker):
            if verbose:
                print(f"[amiga.pip]   skipping optional dep: {req}")
            continue
        try:
            installed_list.extend(install(
                req_name, target=target, cache_dir=cache_dir,
                verbose=verbose, allow_pre=allow_pre,
                _visited=_visited))
        except WheelError as e:
            # A missing dep isn't fatal — report and continue so the
            # user can install what's available. Real pip aborts; we
            # prefer partial-success on the Amiga where every
            # download costs seconds.
            if verbose:
                print(f"[amiga.pip]   WARN: dep {req_name} failed: {e}")

    return installed_list


def _download_http(url, dst):
    """Bare-metal HTTP download (no urllib dependency)."""
    import socket
    scheme_end = url.find("://")
    rest = url[scheme_end + 3:]
    slash = rest.find("/")
    host = rest[:slash] if slash != -1 else rest
    path = rest[slash:] if slash != -1 else "/"
    port = 80
    if ":" in host:
        host, port_s = host.split(":", 1)
        port = int(port_s)

    s = socket.socket()
    s.settimeout(30)
    s.connect((host, port))
    req = (f"GET {path} HTTP/1.0\r\nHost: {host}\r\n"
           f"User-Agent: amiga.pip/0.1\r\nConnection: close\r\n\r\n")
    s.sendall(req.encode())
    buf = b""
    while True:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()

    sep = buf.find(b"\r\n\r\n")
    if sep < 0:
        raise WheelError("bad HTTP response (no header terminator)")
    header = buf[:sep].decode("latin-1")
    body = buf[sep + 4:]
    status = header.split("\r\n", 1)[0]
    if " 200 " not in status:
        raise WheelError(f"HTTP {status}")
    with open(dst, "wb") as f:
        f.write(body)
    return dst
