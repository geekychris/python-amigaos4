"""
amiga.dos — wrappers around dos.library.

Phase A implementation (works today on Python 3.12 OS4 port):
  Uses the built-in `posix`/`os` module for direct filesystem calls
  (mkdir/remove/rename/listdir/stat all forward through newlib to
  IDOS->MakeDir/DeleteFile/Rename/Examine).

  For anything that has no POSIX equivalent (Info, Assign, Execute
  with args, SystemTagList variants), we shell out via `os.system()`
  with stdout captured to `T:amiga_dos_<counter>.tmp` and read back.

Phase B / C (future): direct ctypes / native C module to bypass the
subprocess round-trip.
"""
import os
import shutil
import time
from collections import namedtuple

# ---------------------------------------------------------------------------
# Types the API returns
# ---------------------------------------------------------------------------

VolumeInfo = namedtuple(
    "VolumeInfo",
    "unit device name total_bytes used_bytes free_bytes percent_full errors status",
)

FileInfo = namedtuple(
    "FileInfo",
    "name path size is_dir protection date_iso",
)


class DosError(Exception):
    """Raised by shell-out commands that return non-zero."""


# ---------------------------------------------------------------------------
# Internal helper: run an AmigaDOS command and capture its stdout
# ---------------------------------------------------------------------------

_capture_counter = 0


def _run_capture(cmd):
    """Execute a DOS command; return (returncode, stdout_text).

    Uses a fresh T: tempfile per call, tagged with a monotonic counter
    (newlib on OS4 has no getpid() we can trust)."""
    global _capture_counter
    _capture_counter += 1
    tag = f"T:amiga_dos_{_capture_counter}_{int(time.time())}.tmp"
    rc = os.system(f"{cmd} >{tag}")
    try:
        with open(tag) as f:
            text = f.read()
    except FileNotFoundError:
        text = ""
    try:
        os.remove(tag)
    except OSError:
        pass
    return rc, text


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------

def Execute(cmd, capture=False):
    """Run a DOS command line.

    If capture=True, returns (returncode, stdout_text) via a T: tempfile.
    Otherwise returns the shell exit code from os.system().
    """
    if capture:
        return _run_capture(cmd)
    return os.system(cmd)


def SystemTagList(cmd, **tags):
    """Alias for Execute(cmd).  The `tags` kwargs are accepted for parity
    with the real SystemTagList entry point but ignored in Phase A."""
    return os.system(cmd)


# ---------------------------------------------------------------------------
# Volumes / assigns
# ---------------------------------------------------------------------------

def Info(volume=None):
    """List mounted volumes.  Returns [VolumeInfo, ...].

    If `volume` is given (e.g. 'DH1:'), only that unit's row is returned.
    """
    rc, text = _run_capture("Info")
    if rc != 0:
        raise DosError(f"Info failed rc={rc}")

    results = []
    seen_header = False
    for line in text.splitlines():
        if not line.strip():
            continue
        # Skip until we hit the tabular header line
        if line.lstrip().startswith("Unit"):
            seen_header = True
            continue
        if not seen_header:
            continue
        # 'Volumes available:' terminates the volume section
        if line.startswith(("Volumes", "Mounted")):
            break
        parts = line.split()
        if len(parts) < 7:
            continue
        try:
            unit = parts[0].rstrip(":")
            size_str = parts[1]
            used = int(parts[2].replace(",", ""))
            free = int(parts[3].replace(",", ""))
            pct = int(parts[4].rstrip("%"))
            errors = int(parts[5])
            # Status is either 'Read/Write' or 'Read Only' (two tokens).
            if parts[6] == "Read" and len(parts) > 7 and parts[7] == "Only":
                status = "Read Only"
                name_parts = parts[8:]
            else:
                status = parts[6]
                name_parts = parts[7:]
            name = " ".join(name_parts) if name_parts else unit
            results.append(VolumeInfo(
                unit=unit, device=unit, name=name,
                total_bytes=_parse_size(size_str),
                used_bytes=used, free_bytes=free,
                percent_full=pct, errors=errors, status=status))
        except (ValueError, IndexError):
            continue

    if volume is not None:
        want = volume.rstrip(":").upper()
        results = [v for v in results if v.unit.upper() == want]
    return results


def _parse_size(s):
    """Info prints sizes like '2,047M' or '184K' — return bytes."""
    s = s.replace(",", "")
    if not s:
        return 0
    mult = 1
    if s[-1] in "KMG":
        mult = {"K": 1024, "M": 1024 * 1024, "G": 1024 * 1024 * 1024}[s[-1]]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def Assign(name=None, path=None, defer=False, remove=False):
    """Create, remove, or query an AmigaDOS assign.

        Assign("MYWORK:", "DH1:work")   — create
        Assign("MYWORK:", remove=True)  — remove
        Assign()                        — return {name: path, ...}
    """
    if name is None:
        _, text = _run_capture("Assign")
        return _parse_assigns(text)
    if remove:
        return os.system(f"Assign {name} REMOVE") == 0
    if path is None:
        raise ValueError("Assign(name) requires either path or remove=True")
    flags = " DEFER" if defer else ""
    return os.system(f"Assign {name} {path}{flags}") == 0


def _parse_assigns(text):
    """Best-effort parse of `Assign` output into a name -> path dict."""
    result = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("Volumes", "Directories",
                                  "Devices", "==")):
            continue
        parts = s.split(None, 2)
        if len(parts) >= 2:
            result[parts[0].rstrip(":")] = parts[-1]
    return result


# ---------------------------------------------------------------------------
# Files & directories
# ---------------------------------------------------------------------------

def MakeDir(path):
    """Create a directory.  Returns True on success."""
    os.mkdir(path)
    return True


def DeleteFile(path, recursive=False):
    """Delete a file (or a whole directory tree if recursive=True)."""
    if recursive and os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.isdir(path):
        os.rmdir(path)
    else:
        os.remove(path)
    return True


def Rename(old, new):
    """Rename or move a file / directory."""
    os.rename(old, new)
    return True


def CopyFile(src, dst):
    """Copy a file (preserves mtime via shutil.copy2)."""
    shutil.copy2(src, dst)
    return True


def CurrentDir(path=None):
    """Get or set the current working directory."""
    if path is None:
        return os.getcwd()
    os.chdir(path)
    return path


# ---------------------------------------------------------------------------
# Locks / Examine (Phase A: implemented on top of os.stat + os.walk)
# ---------------------------------------------------------------------------

def Lock(path, mode="r"):
    """Test whether a path is accessible.  Returns the path as an opaque
    handle if OK, or None if not.  Phase A doesn't hold a real dos.Lock —
    every Lock() returns immediately."""
    return path if os.access(path, os.F_OK) else None


def Examine(path):
    """Return a FileInfo for a single path."""
    st = os.stat(path)
    return _stat_to_fileinfo(path, st)


def _stat_to_fileinfo(path, st):
    name = os.path.basename(path.rstrip("/:")) or path
    is_dir = os.path.isdir(path)
    # OS4 doesn't have real POSIX perms; encode simply.
    prot = "rwed" if st.st_mode & 0o200 else "r-e-"
    try:
        date_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.st_mtime))
    except (OSError, ValueError):
        date_iso = ""
    return FileInfo(name=name, path=path, size=st.st_size,
                    is_dir=is_dir, protection=prot, date_iso=date_iso)


def walk(top, followlinks=False):
    """Recursively walk a directory tree.  Yields the same
    (dirpath, dirnames, filenames) tuples as os.walk.  On Amiga, use
    volume paths (e.g. 'DH1:pytests')."""
    return os.walk(top, followlinks=followlinks)


def listdir(path):
    """Return the list of entries in a directory (short names, no path)."""
    return os.listdir(path)
