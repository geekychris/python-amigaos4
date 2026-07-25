"""hello_dos — filesystem introspection via amiga.dos.

Run on the target with:
    DH1:python-os4 DH1:pytests/examples/hello_dos.py

Everything in this script works TODAY on the OS4 Python port (Phase A):
uses only the built-in `os`/`posix` module plus `os.system()`
shell-outs to stock OS4 CLI tools.
"""
import sys, os

# Make amiga_bindings/ importable — location depends on how the tree
# was deployed.  Adjust the path if you put it elsewhere.
sys.path.insert(0, "DH1:pytests/amiga_bindings")

import amiga.dos as dos


def show_volumes():
    print("=== Mounted volumes ===")
    for v in dos.Info():
        print(f"  {v.unit:>10}: {v.name!s:<12}  free={v.free_bytes:>12}  {v.status}")


def show_assigns():
    print("\n=== First few assigns ===")
    assigns = dos.Assign()
    for k in sorted(assigns)[:12]:
        print(f"  {k:>16} -> {assigns[k]}")


def show_dev_tree():
    print("\n=== DH1:pytests/language tree ===")
    for dirpath, dirs, files in dos.walk("DH1:pytests/language"):
        prefix = "  " + dirpath
        print(f"{prefix}  ({len(files)} files, {len(dirs)} dirs)")


def show_python_binary():
    print("\n=== Examine DH1:python-os4 ===")
    info = dos.Examine("DH1:python-os4")
    print(f"  name       {info.name}")
    print(f"  size       {info.size:,} bytes")
    print(f"  is_dir     {info.is_dir}")
    print(f"  protection {info.protection}")
    print(f"  mtime      {info.date_iso}")


def demo_execute():
    print("\n=== Executing 'echo hello via SystemTagList' ===")
    rc, out = dos.Execute("echo hello via SystemTagList", capture=True)
    print(f"  rc={rc}, stdout={out.strip()!r}")


if __name__ == "__main__":
    show_volumes()
    show_assigns()
    show_dev_tree()
    show_python_binary()
    demo_execute()
    print("\nhello_dos: OK")
