#!/usr/bin/env python3
"""s3 — command-line front end for amiga.s3.

Single dispatcher script covering the day-to-day verbs. Reads
endpoint + creds from env vars (S3_ENDPOINT, S3_ACCESS, S3_SECRET,
S3_INSECURE). Run `s3-env` (AmigaDOS script alongside this file) to
set them for a local MinIO instance, or `s3-env-play` for the
public MinIO sandbox.

Usage:
  s3 ls                          list buckets
  s3 ls BUCKET                   list top of a bucket
  s3 ls BUCKET/PREFIX            list under a prefix
  s3 put LOCAL     BUCKET/KEY    upload a file
  s3 get BUCKET/KEY LOCAL        download a file
  s3 cat BUCKET/KEY              dump object to stdout
  s3 rm  BUCKET/KEY              delete an object
  s3 cp  BUCKET/SRC BUCKET/DST   copy (via download+upload — no
                                  server-side COPY yet)
  s3 mv  BUCKET/SRC BUCKET/DST   move (cp + rm)
  s3 stat BUCKET/KEY             show size + etag + content-type
  s3 mb  BUCKET                  (not yet — use `mc mb` host-side)
  s3 sync LOCAL BUCKET/PREFIX    delegate to s3sync.py

Both `s3://bucket/key` and `bucket/key` forms accepted for paths.

Config:
  S3_ENDPOINT   host:port (e.g. 10.0.2.2:9000)
  S3_ACCESS     access key
  S3_SECRET     secret key
  S3_INSECURE   "1" for self-signed TLS (default when unset)
"""
import os
import sys

sys.path.insert(0, "DH1:pytests/amiga_bindings")

try:
    from amiga import s3 as _s3
except ImportError:
    print("s3: amiga.s3 not importable — is DH1:pytests/amiga_bindings "
          "on the path?", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------- config

def _client():
    ep = os.environ.get("S3_ENDPOINT", _s3.PLAY_ENDPOINT)
    ak = os.environ.get("S3_ACCESS",   _s3.PLAY_ACCESS)
    sk = os.environ.get("S3_SECRET",   _s3.PLAY_SECRET)
    insecure = os.environ.get("S3_INSECURE", "1") == "1"
    return _s3.S3Client(ep, ak, sk, insecure_tls=insecure)


def _split(spec):
    """spec is bucket, bucket/key, or s3://bucket/key.

    Returns (bucket, key). key='' if only bucket given."""
    if spec.startswith("s3://"):
        spec = spec[5:]
    spec = spec.lstrip("/")
    if "/" not in spec:
        return spec, ""
    b, _, k = spec.partition("/")
    return b, k


def _fmt_size(n):
    return f"{n:>10d}"


# ---------------------------------------------------------------- verbs

def cmd_ls(args):
    c = _client()
    if not args:
        # bucket list
        for b in c.list_buckets():
            print(f"{b.get('creation_date','?')[:19]}  {b['name']}")
        return 0
    bucket, prefix = _split(args[0])
    prefix_slash = prefix + "/" if prefix else ""
    objs = c.list_objects(bucket, prefix=prefix_slash, max_keys=1000)
    # Collapse pseudo-folders (unique first path segment beyond prefix).
    folders = set()
    files = []
    for o in objs:
        rel = o["key"][len(prefix_slash):]
        if "/" in rel:
            folders.add(rel.split("/", 1)[0])
        elif rel:
            files.append((o["size"], o["last_modified"][:19], rel))
    for f in sorted(folders):
        print(f"{'  <DIR>':>10}                        {f}/")
    for size, ts, name in sorted(files, key=lambda t: t[2]):
        print(f"{_fmt_size(size)}  {ts}  {name}")
    if not folders and not files:
        print(f"(empty: s3://{bucket}/{prefix_slash})")
    return 0


def cmd_put(args):
    if len(args) != 2:
        return _usage()
    local, remote = args
    bucket, key = _split(remote)
    if not key:
        # If they gave just a bucket, use local's basename
        key = os.path.basename(local)
    with open(local, "rb") as f:
        data = f.read()
    hdrs = _client().put_object(bucket, key, data)
    etag = hdrs.get("etag", "?").strip('"')
    print(f"{len(data)} bytes -> s3://{bucket}/{key}   etag {etag}")
    return 0


def cmd_get(args):
    if len(args) != 2:
        return _usage()
    remote, local = args
    bucket, key = _split(remote)
    data = _client().get_object(bucket, key)
    # If local is a directory, write into it with the key basename
    if os.path.isdir(local):
        local = os.path.join(local, os.path.basename(key))
    with open(local, "wb") as f:
        f.write(data)
    print(f"s3://{bucket}/{key} -> {local}   {len(data)} bytes")
    return 0


def cmd_cat(args):
    if len(args) != 1:
        return _usage()
    bucket, key = _split(args[0])
    data = _client().get_object(bucket, key)
    # Write to stdout as bytes. If the terminal doesn't like binary,
    # redirect to a file with '>'.
    sys.stdout.buffer.write(data) if hasattr(sys.stdout, "buffer") else sys.stdout.write(data.decode("utf-8", "replace"))
    return 0


def cmd_rm(args):
    if len(args) != 1:
        return _usage()
    bucket, key = _split(args[0])
    _client().delete_object(bucket, key)
    print(f"removed s3://{bucket}/{key}")
    return 0


def cmd_cp(args):
    if len(args) != 2:
        return _usage()
    sb, sk = _split(args[0])
    db, dk = _split(args[1])
    c = _client()
    data = c.get_object(sb, sk)
    c.put_object(db, dk, data)
    print(f"s3://{sb}/{sk} -> s3://{db}/{dk}  {len(data)} bytes")
    return 0


def cmd_mv(args):
    if len(args) != 2:
        return _usage()
    rc = cmd_cp(args)
    if rc != 0:
        return rc
    sb, sk = _split(args[0])
    _client().delete_object(sb, sk)
    print(f"removed source s3://{sb}/{sk}")
    return 0


def cmd_stat(args):
    if len(args) != 1:
        return _usage()
    bucket, key = _split(args[0])
    info = _client().stat_object(bucket, key)
    for k in ("size", "etag", "content_type", "last_modified"):
        print(f"  {k:<15s} {info.get(k, '')}")
    return 0


def cmd_mb(args):
    print("s3 mb: bucket creation not yet wired into amiga.s3.",
          file=sys.stderr)
    print("       use  `docker exec minio-amiga mc mb local/<name>`",
          file=sys.stderr)
    return 3


def cmd_sync(args):
    """Hand off to s3sync — same env vars, richer flag surface."""
    here = os.path.dirname(os.path.abspath(__file__))
    # Prefer the sibling s3sync.py if present; else fall back to
    # DH1:pytests/examples/s3sync.py which the deploy script places.
    for candidate in (os.path.join(here, "s3sync.py"),
                      "DH1:pytests/examples/s3sync.py"):
        if os.path.exists(candidate):
            os.execvp("DH1:python-os4",
                       ["DH1:python-os4", candidate] + args)
    print("s3 sync: s3sync.py not found", file=sys.stderr)
    return 3


# ---------------------------------------------------------------- dispatch

VERBS = {
    "ls":   cmd_ls,
    "put":  cmd_put,
    "get":  cmd_get,
    "cat":  cmd_cat,
    "rm":   cmd_rm,
    "cp":   cmd_cp,
    "mv":   cmd_mv,
    "stat": cmd_stat,
    "mb":   cmd_mb,
    "sync": cmd_sync,
}


def _usage():
    print(__doc__.strip(), file=sys.stderr)
    return 2


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        return _usage()
    verb, *rest = argv
    fn = VERBS.get(verb)
    if not fn:
        print(f"s3: unknown verb: {verb!r}", file=sys.stderr)
        print(f"    known: {' '.join(VERBS)}", file=sys.stderr)
        return 2
    try:
        return fn(rest)
    except _s3.S3Error as e:
        print(f"s3: S3Error {e.status} {e.code}: {e.message}",
              file=sys.stderr)
        return 1
    except Exception as e:
        print(f"s3: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
