"""Offline tests for amiga.pip.cache — content-addressed local storage
of downloaded wheels."""
import hashlib
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "amiga_bindings"))

_stub = types.ModuleType("amiga.https")
_stub.get = lambda *a, **k: (0, {}, b"")
sys.modules["amiga.https"] = _stub
_pkg = types.ModuleType("amiga")
_pkg.__path__ = [os.path.join(HERE, "..", "amiga_bindings", "amiga")]
sys.modules["amiga"] = _pkg

from amiga.pip import cache  # noqa: E402


class Cache(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="amigapip-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cache_path_uses_basename(self):
        p = cache.cache_path_for(
            "https://example.com/x/y/foo-1.0.0-py3-none-any.whl",
            cache_dir=self.tmp)
        self.assertEqual(os.path.basename(p),
                         "foo-1.0.0-py3-none-any.whl")
        self.assertTrue(p.startswith(self.tmp))

    def test_sha256_matches_hashlib(self):
        data = b"hello wheel"
        p = os.path.join(self.tmp, "x.whl")
        with open(p, "wb") as f:
            f.write(data)
        self.assertEqual(cache.sha256_file(p),
                         hashlib.sha256(data).hexdigest())

    def test_verify_missing(self):
        p = os.path.join(self.tmp, "nope.whl")
        self.assertFalse(cache.verify(p, "0" * 64))

    def test_verify_hash_mismatch(self):
        p = os.path.join(self.tmp, "x.whl")
        with open(p, "wb") as f:
            f.write(b"data")
        self.assertFalse(cache.verify(p, "0" * 64))

    def test_verify_hash_match(self):
        data = b"data"
        p = os.path.join(self.tmp, "x.whl")
        with open(p, "wb") as f:
            f.write(data)
        self.assertTrue(cache.verify(p,
                        hashlib.sha256(data).hexdigest()))

    def test_verify_empty_hash_only_checks_existence(self):
        p = os.path.join(self.tmp, "x.whl")
        self.assertFalse(cache.verify(p, ""))
        with open(p, "wb") as f:
            f.write(b"anything")
        self.assertTrue(cache.verify(p, ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
