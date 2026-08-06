"""amiga.pip CLI — run as `python-os4 -m amiga.pip [verb] [args]`.

Verbs:
  install PKG   — resolve PKG on PyPI, download+install with deps
  list          — show installed packages
  uninstall PKG — remove PKG's files (best-effort)

No fork()/subprocess involved; everything is in-process.
"""
import sys


def _usage():
    print("usage: python -m amiga.pip <verb> [args]")
    print("  install PKG [--pre] [--target DIR]")
    print("             [--index-url URL] [--extra-index-url URL]...")
    print("  list       [--target DIR]")
    print("  uninstall PKG [--target DIR]")


def _parse_kv(args):
    """Very small --foo VALUE parser. Repeated --key VALUE builds a
    list; single occurrences are stored as strings. Returns
    (positional, kv_dict)."""
    pos, kv = [], {}
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                value = args[i + 1]
                if key in kv:
                    if isinstance(kv[key], list):
                        kv[key].append(value)
                    else:
                        kv[key] = [kv[key], value]
                else:
                    kv[key] = value
                i += 2
            else:
                kv[key] = True
                i += 1
        else:
            pos.append(a)
            i += 1
    return pos, kv


def main(argv=None):
    from amiga import pip
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        _usage()
        return 2
    verb, args = argv[0], argv[1:]
    pos, kv = _parse_kv(args)
    target = kv.get("target")
    if verb == "install":
        if not pos:
            _usage()
            return 2
        # Index URL flags. --extra-index-url may repeat.
        index_url = kv.get("index-url")
        extra = kv.get("extra-index-url", [])
        if isinstance(extra, str):
            extra = [extra]
        try:
            installed = pip.install(pos[0], target=target,
                                    allow_pre=bool(kv.get("pre")),
                                    index_url=index_url,
                                    extra_index_urls=tuple(extra))
        except pip.WheelError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not installed:
            print("(nothing to do)")
            return 0
        for p in installed:
            print(f"installed: {p.name} {p.version}")
        return 0
    if verb == "list":
        pkgs = pip.list_installed(target=target)
        if not pkgs:
            print("(no packages installed)")
            return 0
        for p in sorted(pkgs, key=lambda p: p.name.lower()):
            print(f"{p.name:30s} {p.version}")
        return 0
    if verb == "uninstall":
        if not pos:
            _usage()
            return 2
        ok = pip.uninstall(pos[0], target=target)
        print("removed" if ok else "not found")
        return 0 if ok else 1
    print(f"unknown verb: {verb!r}", file=sys.stderr)
    _usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
