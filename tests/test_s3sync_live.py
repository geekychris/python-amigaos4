"""Mac-side smoke test for s3sync — uses the same requests shim of
amiga.https that test_s3_live.py uses. Runs a temp-dir push, then a
pull into a second temp dir, verifies the results match, cleans up."""
import os, sys, types, tempfile, uuid, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(REPO, "amiga_bindings"))

# Same shim as test_s3_live.py — swap amiga.https for a
# requests-backed one so we can drive the sync without QEMU.
import requests

def _fetch(url, method="GET", body=None, headers=None, timeout=30,
           insecure=False, **_):
    kw = {"timeout": timeout, "verify": not insecure}
    if headers:
        kw["headers"] = headers
    if body is not None:
        kw["data"] = body
    r = requests.request(method, url, **kw)
    return r.status_code, {k.lower(): v for k, v in r.headers.items()}, r.content

_https_stub = types.ModuleType("amiga.https")
_https_stub.fetch = _fetch
sys.modules["amiga.https"] = _https_stub
_pkg = types.ModuleType("amiga")
_pkg.__path__ = [os.path.join(REPO, "amiga_bindings", "amiga")]
sys.modules["amiga"] = _pkg

from amiga import s3

# --- override the s3sync module's DH1-specific path insert ---
sys.path.insert(0, os.path.join(REPO, "examples"))
# The example does `for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)`
# on import, which is harmless on Mac (that dir doesn't exist), but
# we also need amiga.s3 (already imported), so the module import
# below succeeds.
import s3sync


def main():
    prefix = f"amiga-s3sync-test/{uuid.uuid4().hex[:10]}"
    client = s3.play_client()
    buckets = client.list_buckets()
    if not buckets:
        print("no buckets on play.min.io")
        return 1
    bucket = buckets[0]["name"]
    remote_spec = f"{bucket}:{prefix}"

    with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dst:
        # Seed source with a few files (incl. a subdir).
        (open(os.path.join(src, "top.txt"), "w")
         .write("top level\n"))
        os.makedirs(os.path.join(src, "sub"))
        open(os.path.join(src, "sub", "a.txt"), "w").write("nested a\n")
        open(os.path.join(src, "sub", "b.txt"), "w").write("nested b longer file\n")

        # Push. Use our environment vars to point at play.min.io.
        os.environ["S3_ENDPOINT"] = s3.PLAY_ENDPOINT
        os.environ["S3_ACCESS"] = s3.PLAY_ACCESS
        os.environ["S3_SECRET"] = s3.PLAY_SECRET
        os.environ["S3_INSECURE"] = "0"     # requests can verify certs

        print("=== PUSH ===")
        rc = s3sync.main([src, remote_spec])
        assert rc == 0, f"push rc={rc}"

        print("\n=== LIST ===")
        rc = s3sync.main(["--list", remote_spec])
        assert rc == 0

        print("\n=== PULL ===")
        rc = s3sync.main(["--down", dst, remote_spec])
        assert rc == 0

        # Verify round-trip.
        for rel in ("top.txt", "sub/a.txt", "sub/b.txt"):
            src_p = os.path.join(src, rel.replace("/", os.sep))
            dst_p = os.path.join(dst, rel.replace("/", os.sep))
            with open(src_p, "rb") as f:
                src_b = f.read()
            with open(dst_p, "rb") as f:
                dst_b = f.read()
            assert src_b == dst_b, f"{rel} round-trip mismatch"
        print("\nround-trip OK — src == dst byte-identical")

        # Modify a file, re-push, verify only that one gets sent.
        open(os.path.join(src, "sub", "b.txt"), "w").write("CHANGED\n")
        print("\n=== PUSH after edit (should be 1 update, 2 skip) ===")
        rc = s3sync.main([src, remote_spec])
        assert rc == 0

        # Delete a local file, push with --delete, verify remote drops it.
        os.remove(os.path.join(src, "top.txt"))
        print("\n=== PUSH --delete after local rm (should delete top.txt on remote) ===")
        rc = s3sync.main([src, remote_spec, "--delete"])
        assert rc == 0

        # Cleanup remote — every key under the prefix.
        for o in client.list_objects(bucket, prefix=prefix + "/"):
            client.delete_object(bucket, o["key"])
        print("\ncleanup ok")

    print("\nall s3sync live checks passed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except s3.S3Error as e:
        print(f"S3Error {e.status} {e.code}: {e.message}")
        sys.exit(1)
