"""Offline integration test for amiga.pip.install() — mocks the HTTPS
layer to feed canned PyPI JSON + canned wheel bytes, verifies:

- resolver picks the right version
- SHA256 verify happens
- dep walker recurses into non-optional Requires-Dist
- extras / marker-guarded deps are skipped
- cache short-circuits second install of the same name
"""
import hashlib
import json
import os
import sys
import tempfile
import types
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "amiga_bindings"))


# ---------------------------------------------------------------------------
# Mock the transport — record every URL requested and reply from a
# scripted dict so we can assert on the call sequence.
# ---------------------------------------------------------------------------

_MOCK_RESPONSES = {}
_MOCK_CALLS = []


def _mock_get(url, *args, **kw):
    _MOCK_CALLS.append(url)
    if url in _MOCK_RESPONSES:
        return _MOCK_RESPONSES[url]
    return (404, {}, b"not found")


_stub = types.ModuleType("amiga.https")
_stub.get = _mock_get
_stub.fetch = _mock_get
sys.modules["amiga.https"] = _stub

_pkg = types.ModuleType("amiga")
_pkg.__path__ = [os.path.join(HERE, "..", "amiga_bindings", "amiga")]
sys.modules["amiga"] = _pkg

from amiga import pip as amiga_pip  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: build a minimal valid wheel in memory.
# ---------------------------------------------------------------------------

def _build_wheel(name, version, requires_dist=(), extra_files=None):
    """Return the raw bytes of a minimal PEP-427 wheel that
    install_wheel will accept."""
    import io
    buf = io.BytesIO()
    dist_info = f"{name.replace('-', '_')}-{version}.dist-info"
    with zipfile.ZipFile(buf, "w") as z:
        metadata_lines = [
            "Metadata-Version: 2.1",
            f"Name: {name}",
            f"Version: {version}",
        ]
        for r in requires_dist:
            metadata_lines.append(f"Requires-Dist: {r}")
        metadata_lines.append("")
        metadata_lines.append("")   # end of headers
        z.writestr(f"{dist_info}/METADATA", "\n".join(metadata_lines))
        z.writestr(f"{dist_info}/WHEEL",
                   "Wheel-Version: 1.0\nGenerator: test\n"
                   "Root-Is-Purelib: true\nTag: py3-none-any\n")
        # Actual package payload — a tiny top-level module.
        z.writestr(f"{name.replace('-', '_')}/__init__.py",
                   f"__version__ = {version!r}\n")
        for path, content in (extra_files or {}).items():
            z.writestr(path, content)
    return buf.getvalue()


def _wheel_filename(name, version):
    return f"{name.replace('-', '_')}-{version}-py3-none-any.whl"


def _script_pypi(name, version, requires_dist=(), wheel_bytes=None):
    """Register a mock PyPI JSON + mock wheel download."""
    if wheel_bytes is None:
        wheel_bytes = _build_wheel(name, version, requires_dist)
    fname = _wheel_filename(name, version)
    wheel_url = f"https://files.pythonhosted.org/packages/xx/{fname}"
    sha = hashlib.sha256(wheel_bytes).hexdigest()
    j = {
        "info": {
            "name": name, "version": version,
            "requires_dist": list(requires_dist),
        },
        "releases": {
            version: [{"filename": fname,
                       "url": wheel_url,
                       "digests": {"sha256": sha}}]
        }
    }
    _MOCK_RESPONSES[f"https://pypi.org/pypi/{name}/json"] = (
        200, {}, json.dumps(j).encode("utf-8"))
    _MOCK_RESPONSES[wheel_url] = (200, {}, wheel_bytes)


# ---------------------------------------------------------------------------
# Fixtures + reset between tests
# ---------------------------------------------------------------------------

class InstallFlow(unittest.TestCase):

    def setUp(self):
        _MOCK_RESPONSES.clear()
        _MOCK_CALLS.clear()
        self.target = tempfile.mkdtemp(prefix="amigapip-target-")
        self.cache = tempfile.mkdtemp(prefix="amigapip-cache-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.target, ignore_errors=True)
        shutil.rmtree(self.cache, ignore_errors=True)

    # -- basic --

    def test_install_no_deps(self):
        _script_pypi("chardet", "5.2.0", requires_dist=())
        result = amiga_pip.install("chardet", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].name, "chardet")
        self.assertEqual(result[0].version, "5.2.0")
        # Package was extracted to target.
        self.assertTrue(os.path.isfile(
            os.path.join(self.target, "chardet", "__init__.py")))

    def test_install_transitive_deps(self):
        _script_pypi("a", "1.0", requires_dist=("b", "c"))
        _script_pypi("b", "1.0", requires_dist=("d",))
        _script_pypi("c", "1.0", requires_dist=())
        _script_pypi("d", "1.0", requires_dist=())
        result = amiga_pip.install("a", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        names = sorted(p.name for p in result)
        self.assertEqual(names, ["a", "b", "c", "d"])

    def test_skips_extras_and_platform_markers(self):
        _script_pypi("core", "1.0", requires_dist=(
            "required-dep",
            'optional-dep ; extra == "socks"',
            'winonly ; sys_platform == "win32"',
        ))
        _script_pypi("required-dep", "1.0", requires_dist=())
        result = amiga_pip.install("core", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        # PEP 491 wheel-filename escaping: `-` in dist name becomes `_`
        # in the on-disk .dist-info name, so InstalledPackage.name uses
        # the underscore form. Canonical comparison happens inside
        # install() via _canonical_name().
        names = sorted(p.name for p in result)
        self.assertEqual(names, ["core", "required_dep"])

    def test_cache_prevents_redownload(self):
        _script_pypi("solo", "1.0", requires_dist=())
        amiga_pip.install("solo", target=self.target,
                          cache_dir=self.cache, verbose=False)
        wheel_url = next(u for u in _MOCK_CALLS if u.endswith(".whl"))
        first_call_count = _MOCK_CALLS.count(wheel_url)
        _MOCK_CALLS.clear()

        # Nuke the target so install would run again; keep cache.
        import shutil
        shutil.rmtree(self.target)
        os.makedirs(self.target)

        amiga_pip.install("solo", target=self.target,
                          cache_dir=self.cache, verbose=False)
        second_call_count = _MOCK_CALLS.count(wheel_url)
        self.assertEqual(first_call_count, 1)
        self.assertEqual(second_call_count, 0,
            "wheel should not be re-downloaded when cached")

    def test_already_installed_skipped(self):
        _script_pypi("thing", "1.0", requires_dist=())
        amiga_pip.install("thing", target=self.target,
                          cache_dir=self.cache, verbose=False)
        _MOCK_CALLS.clear()
        result = amiga_pip.install("thing", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        self.assertEqual(result, [])
        self.assertEqual(_MOCK_CALLS, [],
            "already-installed package should not hit the network")

    def test_diamond_dep_visited_only_once(self):
        # a → b, c ; b → shared ; c → shared
        _script_pypi("a", "1.0", requires_dist=("b", "c"))
        _script_pypi("b", "1.0", requires_dist=("shared",))
        _script_pypi("c", "1.0", requires_dist=("shared",))
        _script_pypi("shared", "1.0", requires_dist=())
        result = amiga_pip.install("a", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        names = sorted(p.name for p in result)
        self.assertEqual(names, ["a", "b", "c", "shared"])
        shared_json_calls = _MOCK_CALLS.count(
            "https://pypi.org/pypi/shared/json")
        self.assertEqual(shared_json_calls, 1,
            "diamond dep should be resolved once")

    def test_sha256_mismatch_raises(self):
        _script_pypi("bad", "1.0", requires_dist=())
        # Corrupt the wheel response — same URL, garbled bytes.
        for url, (status, hdr, _) in list(_MOCK_RESPONSES.items()):
            if url.endswith(".whl"):
                _MOCK_RESPONSES[url] = (status, hdr, b"corrupted")
        with self.assertRaises(amiga_pip.WheelError) as cm:
            amiga_pip.install("bad", target=self.target,
                              cache_dir=self.cache, verbose=False)
        self.assertIn("SHA256", str(cm.exception))

    def test_normalises_name_via_canonicalisation(self):
        # PEP 503: charset-normalizer and charset_normalizer are same
        _script_pypi("charset-normalizer", "3.0", requires_dist=())
        # Someone requests the hyphen form
        result = amiga_pip.install("charset-normalizer", target=self.target,
                                    cache_dir=self.cache, verbose=False)
        # On-disk dist-info uses underscored form per PEP 491.
        self.assertEqual(result[0].name, "charset_normalizer")
        # Now try again with hyphen form — should be skipped because
        # _canonical_name() sees both as the same package.
        _MOCK_CALLS.clear()
        result2 = amiga_pip.install("charset-normalizer",
                                    target=self.target,
                                    cache_dir=self.cache, verbose=False)
        self.assertEqual(result2, [],
            "canonicalised name should short-circuit already-installed")


class CanonicalName(unittest.TestCase):

    def test_lowercases(self):
        self.assertEqual(amiga_pip._canonical_name("PySocks"), "pysocks")

    def test_squashes_underscore_hyphen_dot(self):
        for form in ("charset-normalizer", "charset_normalizer",
                     "charset.normalizer", "charset__normalizer"):
            self.assertEqual(amiga_pip._canonical_name(form),
                             "charset-normalizer", form)


if __name__ == "__main__":
    unittest.main(verbosity=2)
