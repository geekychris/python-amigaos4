"""
amiga.pip — subprocess-free wheel installer for the OS4 Python port.

Real pip needs fork+exec (via subprocess) to run isolated build backends
and hash verification helpers.  Newlib on OS4 has no fork(), so the
`pip install X` command line never gets past its startup.

This module offers just the bits that DO work today:

  - install_wheel(path_to_wheel, target=DH1:lib)  — pure-Python wheel
      (`*-py3-none-any.whl`) extraction into a target dir on sys.path.
      Skips *.dist-info metadata but keeps the RECORD so uninstall
      works.  Compiled-C wheels are refused.

  - list_installed(target=DH1:lib) — walks *.dist-info dirs and
      returns a list of (name, version, wheel_path) tuples.

  - uninstall(name, target=DH1:lib) — removes files listed in that
      wheel's RECORD.

  - download_wheel(url, dst)  — HTTP-only (no HTTPS/SSL yet).
      Useful when combined with a curated wheel mirror.

Real pip is still shipped in DH1:lib/pip (we extracted the bundled
wheel).  `python -m pip` will fail at any subprocess boundary, but
you can still `import pip; pip.__version__` for library-level use.
"""
import os
import sys
import zipfile
from collections import namedtuple

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
    """Fetch a wheel over HTTP (no HTTPS yet — needs _ssl module).

    For pypi.org (HTTPS-only), preload wheels on the host and push
    with amiga_push_file, then install_wheel() from disk.
    """
    if url.startswith("https://"):
        raise WheelError("HTTPS not supported yet (needs _ssl / AmiSSL)")

    import socket
    # Very small manual HTTP GET so we don't depend on urllib being installed.
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

    # Split headers / body
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
