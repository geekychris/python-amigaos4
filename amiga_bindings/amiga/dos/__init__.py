"""
amiga.dos — dos.library wrappers.

Everything here is a thin Python surface over the AmigaDOS SDK:
Execute, Info, Lock, Examine, ExNext, MakeDir, DeleteFile, Rename,
CopyFile, SystemTagList.

Phase B/C: needs ctypes-loaded dos.library or the _amiga C
extension. Nothing works before then.
"""
from amiga import NotImplementedYet


def Execute(command, output_path=None):
    """Run an AmigaDOS shell command.

    Args:
        command: shell command line string
        output_path: file to redirect stdout to, or None for capture

    Returns:
        (rc: int, output: str) — rc = program return code from the shell
    """
    raise NotImplementedYet("B", "amiga.dos.Execute")


def SystemTagList(command, tags=None):
    """Full-power System() call — same as C SystemTagList.

    Preferred over Execute for anything with args since it doesn't
    need to re-parse the shell command line."""
    raise NotImplementedYet("B", "amiga.dos.SystemTagList")


def Info(volume):
    """Query volume info (blocks, blocks free, blocks used, block size).

    Returns:
        dict: {name, total_blocks, used_blocks, free_blocks, block_size, ...}
    """
    raise NotImplementedYet("B", "amiga.dos.Info")


def MakeDir(path):
    """Create a directory. Same as `os.mkdir` but wraps AmigaDOS
    directly for correct volume-path handling on Amiga."""
    raise NotImplementedYet("B", "amiga.dos.MakeDir")


def DeleteFile(path):
    """Delete a file. Amiga's Delete() knows about the various
    protection flags in a way os.remove() might not."""
    raise NotImplementedYet("B", "amiga.dos.DeleteFile")


def Rename(src, dst):
    """Rename a file or directory."""
    raise NotImplementedYet("B", "amiga.dos.Rename")


def CopyFile(src, dst, all_flag=False, clone=False):
    """Copy a file or (with all_flag=True) a directory tree.

    `clone=True` preserves date + protection bits (default in Copy ALL CLONE)."""
    raise NotImplementedYet("B", "amiga.dos.CopyFile")


def Assign(name, path):
    """Create/change/remove an AmigaDOS assign.

    Passing path=None removes the assign."""
    raise NotImplementedYet("B", "amiga.dos.Assign")


def CurrentDir(lock_or_path):
    """Change the current dir (accepts either a Lock or a path string)."""
    raise NotImplementedYet("B", "amiga.dos.CurrentDir")


def Lock(path, mode="r"):
    """Lock a file/directory. Returns an opaque Lock handle to pass
    to Examine/ExNext/CurrentDir/UnLock."""
    raise NotImplementedYet("B", "amiga.dos.Lock")


def Examine(lock):
    """Return dict {name, entry_type, size, protection, comment, days, mins, ticks}
    for a locked file/directory."""
    raise NotImplementedYet("B", "amiga.dos.Examine")


def ExNext(lock, fib):
    """Walk to the next entry in a locked directory. Returns None at end."""
    raise NotImplementedYet("B", "amiga.dos.ExNext")


def walk(root):
    """Convenience: yield (path, is_dir, size, mtime) for every entry
    under `root` — like os.walk but Amiga-native."""
    raise NotImplementedYet("B", "amiga.dos.walk")
