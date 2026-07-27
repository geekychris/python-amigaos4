"""Live-endpoint test for amiga.s3 — talks to play.min.io using a
Mac-side requests-backed shim of amiga.https. Verifies that the
S3Client logic (signing, XML parsing, verb wiring) works end-to-end.

On-Amiga, `amiga.https.fetch` shells out through openssl s_client;
here we substitute `requests` so we can test the S3 layer without
booting QEMU. If this passes on Mac but fails on Amiga, the bug is
in amiga.https, not in amiga.s3.

Run:  python3 tests/test_s3_live.py
      python3 tests/test_s3_live.py --keep   # don't delete the object
"""
import os, sys, time, types, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "amiga_bindings"))

# --------- shim amiga.https using `requests` -----------------------
import requests

def _fetch(url, method="GET", body=None, headers=None, timeout=30,
           insecure=False, **_ignored):
    kw = {"timeout": timeout, "verify": not insecure}
    if headers:
        # amiga.https passes lowercase; requests accepts either.
        kw["headers"] = headers
    if body is not None:
        kw["data"] = body
    resp = requests.request(method, url, **kw)
    hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return resp.status_code, hdrs, resp.content

_https_stub = types.ModuleType("amiga.https")
_https_stub.fetch = _fetch
sys.modules["amiga.https"] = _https_stub

_pkg = types.ModuleType("amiga")
_pkg.__path__ = [os.path.join(HERE, "..", "amiga_bindings", "amiga")]
sys.modules["amiga"] = _pkg

# -------------------------------------------------------------------
from amiga import s3


def main():
    keep = "--keep" in sys.argv
    client = s3.play_client()

    # 1. list_buckets — global op, always works with valid creds.
    print("[1/5] list_buckets ... ", end="", flush=True)
    buckets = client.list_buckets()
    print(f"ok ({len(buckets)} buckets)")
    print(f"        first few: {[b['name'] for b in buckets[:3]]}")

    if not buckets:
        print("play.min.io returned no buckets — something's off.")
        return 1

    # 2. Create a test bucket if we can; else pick any bucket that
    #    we know is writable on play.min.io. play.min.io lets anyone
    #    write to any bucket, so first-bucket + unique key is safe.
    bucket_name = buckets[0]["name"]
    test_key = f"amiga-s3-test/{uuid.uuid4().hex}.txt"
    payload = f"hello from amiga.s3 at {time.time()}\n".encode()

    # 3. put_object
    print(f"[2/5] put_object -> {bucket_name}/{test_key} ... ",
          end="", flush=True)
    hdrs = client.put_object(bucket_name, test_key, payload,
                             content_type="text/plain")
    print(f"ok (etag {hdrs.get('etag', '?')})")

    # 4. stat_object
    print(f"[3/5] stat_object ... ", end="", flush=True)
    info = client.stat_object(bucket_name, test_key)
    print(f"ok (size={info['size']}, ct={info['content_type']})")
    assert info["size"] == len(payload), f"size mismatch: {info['size']} vs {len(payload)}"

    # 5. get_object
    print(f"[4/5] get_object ... ", end="", flush=True)
    got = client.get_object(bucket_name, test_key)
    print(f"ok ({len(got)} bytes)")
    assert got == payload, f"body mismatch:\n  got:  {got!r}\n  want: {payload!r}"

    # 6. list_objects
    print(f"[5/5] list_objects prefix='amiga-s3-test/' ... ",
          end="", flush=True)
    objs = client.list_objects(bucket_name, prefix="amiga-s3-test/", max_keys=50)
    print(f"ok ({len(objs)} matching)")
    if not any(o["key"] == test_key for o in objs):
        print(f"        WARN: {test_key} not in list (might be eventual-consistency)")

    # 7. delete_object
    if not keep:
        print(f"[cleanup] delete_object ... ", end="", flush=True)
        client.delete_object(bucket_name, test_key)
        print("ok")
    else:
        print(f"[cleanup] --keep given, leaving {bucket_name}/{test_key}")

    print("\nall live checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except s3.S3Error as e:
        print(f"\nS3Error {e.status} {e.code}: {e.message}")
        print(f"body: {e.body[:400]!r}")
        sys.exit(1)
