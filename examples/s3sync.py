"""s3sync.py — one-way directory sync between an Amiga volume and S3.

Uses every verb in amiga.s3 in a real workflow:
    list_objects  to enumerate the S3 side
    stat_object   to check size before deciding to re-upload
    put_object    to push new / changed local files
    get_object    to pull new / changed remote files
    delete_object to prune on the destination when --delete is set

Comparison is by size only (fast, no hashing). Good enough for text
files and small binaries; the trade-off is that a file edited to the
exact same byte-count won't be re-synced. Add --force to skip the
compare and always overwrite.

Examples:
    push:  DH1:python-os4 s3sync.py RAM:notes/ mybucket:backups/notes
    pull:  DH1:python-os4 s3sync.py --down RAM:notes/ mybucket:backups/notes
    view:  DH1:python-os4 s3sync.py --list mybucket:backups/notes
    dry:   DH1:python-os4 s3sync.py --dry-run RAM:notes/ mybucket:backups/notes

Auth: uses play.min.io + sandbox creds by default. Override with env
vars S3_ENDPOINT, S3_ACCESS, S3_SECRET before running.
"""
import os
import sys
import time

sys.path.insert(0, "DH1:pytests/amiga_bindings")
from amiga import s3


def _client():
    endpoint = os.environ.get("S3_ENDPOINT", s3.PLAY_ENDPOINT)
    access = os.environ.get("S3_ACCESS", s3.PLAY_ACCESS)
    secret = os.environ.get("S3_SECRET", s3.PLAY_SECRET)
    return s3.S3Client(endpoint, access, secret,
                       insecure_tls=os.environ.get("S3_INSECURE", "1") == "1")


def _split_remote(spec: str) -> tuple[str, str]:
    """Split 'bucket:prefix/path' into (bucket, prefix). Empty prefix
    if no colon."""
    if ":" not in spec:
        return spec, ""
    bucket, _, prefix = spec.partition(":")
    return bucket, prefix.strip("/")


def _walk_local(root: str) -> dict[str, tuple[str, int]]:
    """Return {rel_path: (abs_path, size)} for every file under root.
    Rel paths use forward slashes so they map cleanly to S3 keys.
    Symlinks + special files skipped."""
    out: dict[str, tuple[str, int]] = {}
    root_abs = os.path.abspath(root)
    for dirpath, _, files in os.walk(root_abs):
        for name in files:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            rel = os.path.relpath(full, root_abs).replace(os.sep, "/")
            out[rel] = (full, st.st_size)
    return out


def _remote_index(client, bucket: str, prefix: str) -> dict[str, int]:
    """Return {rel_key: size} for every object under prefix. The rel
    key drops the prefix so it lines up with local rel paths."""
    out: dict[str, int] = {}
    prefix_slash = prefix + "/" if prefix else ""
    for o in client.list_objects(bucket, prefix=prefix_slash, max_keys=1000):
        key = o["key"]
        rel = key[len(prefix_slash):] if key.startswith(prefix_slash) else key
        if rel:
            out[rel] = o["size"]
    return out


def _remote_key(prefix: str, rel: str) -> str:
    return f"{prefix}/{rel}" if prefix else rel


def cmd_list(remote_spec: str) -> int:
    client = _client()
    bucket, prefix = _split_remote(remote_spec)
    print(f"Listing s3://{bucket}/{prefix}/", flush=True)
    idx = _remote_index(client, bucket, prefix)
    if not idx:
        print("  (empty)")
        return 0
    total = 0
    for rel in sorted(idx):
        size = idx[rel]
        total += size
        print(f"  {size:>10}  {rel}")
    print(f"{len(idx)} object(s), {total} bytes total")
    return 0


def cmd_push(local_dir: str, remote_spec: str, *,
             dry_run: bool, delete: bool, force: bool) -> int:
    client = _client()
    bucket, prefix = _split_remote(remote_spec)
    print(f"Push  {local_dir}  ->  s3://{bucket}/{prefix}/", flush=True)

    local = _walk_local(local_dir)
    remote = _remote_index(client, bucket, prefix)
    print(f"  local:  {len(local)} files", flush=True)
    print(f"  remote: {len(remote)} objects", flush=True)

    n_up = n_skip = n_del = 0
    for rel, (path, size) in sorted(local.items()):
        r_size = remote.get(rel)
        if not force and r_size == size:
            n_skip += 1
            continue
        n_up += 1
        action = "update" if rel in remote else "create"
        print(f"  {action:6} {rel}  ({size}b)", flush=True)
        if dry_run:
            continue
        with open(path, "rb") as f:
            data = f.read()
        client.put_object(bucket, _remote_key(prefix, rel), data)

    if delete:
        stale = [rel for rel in remote if rel not in local]
        for rel in sorted(stale):
            n_del += 1
            print(f"  delete {rel}", flush=True)
            if not dry_run:
                client.delete_object(bucket, _remote_key(prefix, rel))

    print(f"\ndone  uploaded={n_up}  skipped={n_skip}  deleted={n_del}"
          f"{'  (dry-run)' if dry_run else ''}", flush=True)
    return 0


def cmd_pull(local_dir: str, remote_spec: str, *,
             dry_run: bool, delete: bool, force: bool) -> int:
    client = _client()
    bucket, prefix = _split_remote(remote_spec)
    print(f"Pull  s3://{bucket}/{prefix}/  ->  {local_dir}", flush=True)

    remote = _remote_index(client, bucket, prefix)
    local = _walk_local(local_dir) if os.path.exists(local_dir) else {}
    print(f"  remote: {len(remote)} objects", flush=True)
    print(f"  local:  {len(local)} files", flush=True)

    n_dl = n_skip = n_del = 0
    for rel in sorted(remote):
        r_size = remote[rel]
        l_size = local.get(rel, (None, -1))[1]
        if not force and l_size == r_size:
            n_skip += 1
            continue
        n_dl += 1
        print(f"  fetch {rel}  ({r_size}b)", flush=True)
        if dry_run:
            continue
        data = client.get_object(bucket, _remote_key(prefix, rel))
        dst = os.path.join(local_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(dst, "wb") as f:
            f.write(data)

    if delete:
        stale = [rel for rel in local if rel not in remote]
        for rel in sorted(stale):
            n_del += 1
            path = local[rel][0]
            print(f"  delete {path}", flush=True)
            if not dry_run:
                try:
                    os.remove(path)
                except OSError as e:
                    print(f"    (couldn't delete: {e})")

    print(f"\ndone  downloaded={n_dl}  skipped={n_skip}  deleted={n_del}"
          f"{'  (dry-run)' if dry_run else ''}", flush=True)
    return 0


def usage() -> int:
    print(__doc__, flush=True)
    return 2


def main(argv: list[str]) -> int:
    flags = {a for a in argv if a.startswith("--")}
    args = [a for a in argv if not a.startswith("--")]
    dry_run = "--dry-run" in flags
    delete = "--delete" in flags
    force = "--force" in flags
    pull = "--down" in flags

    if "--list" in flags:
        if len(args) != 1:
            return usage()
        return cmd_list(args[0])

    if len(args) != 2:
        return usage()
    local_dir, remote_spec = args
    if pull:
        return cmd_pull(local_dir, remote_spec, dry_run=dry_run,
                        delete=delete, force=force)
    return cmd_push(local_dir, remote_spec, dry_run=dry_run,
                    delete=delete, force=force)


if __name__ == "__main__":
    t0 = time.time()
    try:
        rc = main(sys.argv[1:])
    except s3.S3Error as e:
        print(f"\nS3Error {e.status} {e.code}: {e.message}")
        rc = 1
    except Exception as e:
        print(f"\n{type(e).__name__}: {e}")
        rc = 1
    print(f"({time.time() - t0:.1f}s)", flush=True)
    sys.exit(rc)
