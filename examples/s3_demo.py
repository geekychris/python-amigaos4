"""s3_demo.py — talk to a real S3-compatible endpoint from OS4.

Uses the public MinIO play sandbox (play.min.io) with well-known
credentials. Do NOT put anything sensitive in the test bucket —
anyone in the world can read it.

Verifies the same five operations that pass in the Mac-side live
test:  list_buckets, put_object, stat_object, get_object,
list_objects, delete_object.  If this works end-to-end from OS4, the
whole stack (SigV4 signing → amiga.https shell-out → openssl s_client
→ AmiSSL → bsdsocket TCP → play.min.io) is proven wired.

Requires:
  DH1:openssl       (AmiSSL 5.27+ CLI — same one amiga.https needs)
  DH1:AmiSSL/       (assign AmiSSL: DH1:AmiSSL for cert lookup)
  amiga.https       (already in amiga_bindings)
  amiga.s3          (new — this demo is the first user)
  bsdsocket + net   (rtl8139 up, IP configured — same as amiga.https)

Usage:
  python3 python3:examples/s3_demo.py           — full cycle
  python3 python3:examples/s3_demo.py list      — buckets only
  python3 python3:examples/s3_demo.py --keep    — don't delete
"""
import sys
import time
import uuid

for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
from amiga import s3


def demo_list_only(insecure: bool = False):
    client = s3.play_client(insecure_tls=insecure)
    print("Listing buckets on play.min.io ...", flush=True)
    buckets = client.list_buckets()
    print(f"  {len(buckets)} buckets returned.")
    for b in buckets[:10]:
        print(f"    {b['name']:<40}  {b.get('creation_date','')}")
    if len(buckets) > 10:
        print(f"    ... and {len(buckets)-10} more")


def demo_full(keep: bool, insecure: bool = False):
    client = s3.play_client(insecure_tls=insecure)

    print("[1/5] list_buckets ...", flush=True)
    buckets = client.list_buckets()
    print(f"        ok, {len(buckets)} buckets")
    if not buckets:
        print("        (no buckets — cannot continue)")
        return 1
    bucket = buckets[0]["name"]

    key = f"amiga-s3-test/{uuid.uuid4().hex[:12]}.txt"
    payload = f"hello from OS4 python at {time.time()}\n".encode()

    print(f"[2/5] put_object {bucket}/{key} ({len(payload)}b) ...",
          flush=True)
    hdrs = client.put_object(bucket, key, payload, content_type="text/plain")
    print(f"        ok, etag {hdrs.get('etag', '?')}")

    print(f"[3/5] stat_object ...", flush=True)
    info = client.stat_object(bucket, key)
    print(f"        ok, size={info['size']} ct={info['content_type']!r}")

    print(f"[4/5] get_object ...", flush=True)
    got = client.get_object(bucket, key)
    ok = (got == payload)
    print(f"        ok, {len(got)}b {'[MATCH]' if ok else '[MISMATCH]'}")
    if not ok:
        print(f"        expected: {payload!r}")
        print(f"        got:      {got!r}")
        return 1

    print(f"[5/5] list_objects prefix='amiga-s3-test/' ...", flush=True)
    objs = client.list_objects(bucket, prefix="amiga-s3-test/", max_keys=50)
    found = any(o["key"] == key for o in objs)
    print(f"        ok, {len(objs)} match  [{'FOUND' if found else 'not yet visible'}]")

    if keep:
        print(f"[keep] leaving {bucket}/{key} on server")
    else:
        print(f"[cleanup] delete_object ...", flush=True)
        client.delete_object(bucket, key)
        print("        ok")

    print("\nall S3 verbs worked end-to-end from OS4.", flush=True)
    return 0


def main():
    args = sys.argv[1:]
    insecure = "--insecure" in args
    if "list" in args:
        demo_list_only(insecure=insecure)
        return 0
    keep = "--keep" in args
    try:
        return demo_full(keep, insecure=insecure)
    except s3.S3Error as e:
        print(f"\nS3Error {e.status} {e.code}: {e.message}")
        if e.body:
            print(f"body head: {e.body[:400]!r}")
        return 1
    except Exception as e:
        print(f"\n{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
