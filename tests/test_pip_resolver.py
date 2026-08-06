"""Offline tests for amiga.pip.resolver — feeds mock PyPI JSON to the
resolver and asserts the right (version, wheel_url) is picked.

Runs on macOS/Linux Python; no bridge, no OS4.

    python3 tests/test_pip_resolver.py
"""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "amiga_bindings"))

# Stub amiga.https so `from amiga import https` works during import
# even though we won't call fetch() in the resolver tests.
_stub = types.ModuleType("amiga.https")
_stub.fetch = lambda *a, **kw: (0, {}, b"")
_stub.get   = lambda *a, **kw: (0, {}, b"")
sys.modules["amiga.https"] = _stub
_pkg = types.ModuleType("amiga")
_pkg.__path__ = [os.path.join(HERE, "..", "amiga_bindings", "amiga")]
sys.modules["amiga"] = _pkg

from amiga.pip import resolver  # noqa: E402


# ---------------------------------------------------------------------------
# parse_version
# ---------------------------------------------------------------------------

class VersionParse(unittest.TestCase):

    def test_orders_final_after_pre(self):
        self.assertLess(resolver.parse_version("1.0.0a1"),
                        resolver.parse_version("1.0.0"))
        self.assertLess(resolver.parse_version("1.0.0rc1"),
                        resolver.parse_version("1.0.0"))
        self.assertLess(resolver.parse_version("1.0.0.dev5"),
                        resolver.parse_version("1.0.0a1"))

    def test_semver_ordering(self):
        vs = ["0.9.9", "1.0.0", "1.0.1", "1.1.0", "2.0.0"]
        srt = sorted(vs, key=resolver.parse_version)
        self.assertEqual(srt, vs)

    def test_post_release_after_final(self):
        self.assertLess(resolver.parse_version("1.2.3"),
                        resolver.parse_version("1.2.3.post1"))

    def test_v_prefix_tolerated(self):
        self.assertEqual(resolver.parse_version("v1.2.3"),
                         resolver.parse_version("1.2.3"))

    def test_epoch_beats_release_number(self):
        self.assertLess(resolver.parse_version("999.999.999"),
                        resolver.parse_version("1!0.1"))


class IsPreRelease(unittest.TestCase):

    def test_final_not_pre(self):
        self.assertFalse(resolver.is_pre_release("1.2.3"))
        self.assertFalse(resolver.is_pre_release("2.0"))

    def test_pre_flavours(self):
        for v in ("1.0.0a1", "1.0b2", "1.0rc3", "1.0.dev0", "1.0.pre1"):
            self.assertTrue(resolver.is_pre_release(v), v)

    def test_post_is_not_pre(self):
        self.assertFalse(resolver.is_pre_release("1.0.post1"))


# ---------------------------------------------------------------------------
# is_compatible_wheel
# ---------------------------------------------------------------------------

class WheelCompat(unittest.TestCase):

    def test_pure_python_universal(self):
        self.assertTrue(resolver.is_compatible_wheel(
            "chardet-5.2.0-py3-none-any.whl"))
        self.assertTrue(resolver.is_compatible_wheel(
            "six-1.16.0-py2.py3-none-any.whl"))

    def test_reject_platform_wheels(self):
        self.assertFalse(resolver.is_compatible_wheel(
            "numpy-1.26.4-cp312-cp312-manylinux_2_17_x86_64.whl"))
        self.assertFalse(resolver.is_compatible_wheel(
            "pyzmq-25.1.2-pp310-pypy310_pp73-win_amd64.whl"))

    def test_reject_non_wheels(self):
        self.assertFalse(resolver.is_compatible_wheel(
            "chardet-5.2.0.tar.gz"))
        self.assertFalse(resolver.is_compatible_wheel(""))


# ---------------------------------------------------------------------------
# resolve_from_json
# ---------------------------------------------------------------------------

def _mock_pypi(name, releases):
    """Build a minimal-shape PyPI JSON blob for a name and a dict of
    version → list of file records (filename, url, sha256).
    """
    return {
        "info": {"name": name, "version": max(releases.keys(),
                 key=resolver.parse_version)},
        "releases": {
            v: [{"filename": f["filename"],
                 "url": f["url"],
                 "digests": {"sha256": f.get("sha256", "deadbeef")},
                 "yanked": f.get("yanked", False)}
                for f in flist]
            for v, flist in releases.items()
        },
    }


class Resolve(unittest.TestCase):

    def test_picks_highest_stable(self):
        data = _mock_pypi("chardet", {
            "4.0.0": [{"filename": "chardet-4.0.0-py2.py3-none-any.whl",
                       "url": "https://example.com/chardet-4.0.0.whl"}],
            "5.0.0": [{"filename": "chardet-5.0.0-py3-none-any.whl",
                       "url": "https://example.com/chardet-5.0.0.whl"}],
            "5.2.0": [{"filename": "chardet-5.2.0-py3-none-any.whl",
                       "url": "https://example.com/chardet-5.2.0.whl"}],
        })
        r = resolver.resolve_from_json(data)
        self.assertEqual(r.version, "5.2.0")
        self.assertIn("chardet-5.2.0", r.wheel_url)

    def test_skips_pre_release_by_default(self):
        data = _mock_pypi("foo", {
            "1.0.0":     [{"filename": "foo-1.0.0-py3-none-any.whl",
                           "url": "u1"}],
            "2.0.0rc1":  [{"filename": "foo-2.0.0rc1-py3-none-any.whl",
                           "url": "u2"}],
        })
        r = resolver.resolve_from_json(data)
        self.assertEqual(r.version, "1.0.0")

    def test_allow_pre_flag(self):
        data = _mock_pypi("foo", {
            "1.0.0":     [{"filename": "foo-1.0.0-py3-none-any.whl",
                           "url": "u1"}],
            "2.0.0rc1":  [{"filename": "foo-2.0.0rc1-py3-none-any.whl",
                           "url": "u2"}],
        })
        r = resolver.resolve_from_json(data, allow_pre=True)
        self.assertEqual(r.version, "2.0.0rc1")

    def test_skips_yanked(self):
        data = _mock_pypi("foo", {
            "1.0.0": [{"filename": "foo-1.0.0-py3-none-any.whl",
                       "url": "u1"}],
            "1.1.0": [{"filename": "foo-1.1.0-py3-none-any.whl",
                       "url": "u2", "yanked": True}],
        })
        r = resolver.resolve_from_json(data)
        self.assertEqual(r.version, "1.0.0")

    def test_skips_platform_wheels(self):
        data = _mock_pypi("foo", {
            "1.0.0": [
                {"filename": "foo-1.0.0-cp312-cp312-manylinux2014_x86_64.whl",
                 "url": "u1"},
                {"filename": "foo-1.0.0-py3-none-any.whl", "url": "u2"},
            ],
        })
        r = resolver.resolve_from_json(data)
        self.assertEqual(r.wheel_url, "u2")

    def test_no_pure_wheel_raises(self):
        data = _mock_pypi("foo", {
            "1.0.0": [{"filename": "foo-1.0.0.tar.gz", "url": "u1"}],
        })
        with self.assertRaises(resolver.ResolveError):
            resolver.resolve_from_json(data)

    def test_prefer_specific_version(self):
        data = _mock_pypi("foo", {
            "1.0.0": [{"filename": "foo-1.0.0-py3-none-any.whl", "url": "u1"}],
            "1.1.0": [{"filename": "foo-1.1.0-py3-none-any.whl", "url": "u2"}],
        })
        r = resolver.resolve_from_json(data, prefer_version="1.0.0")
        self.assertEqual(r.version, "1.0.0")
        self.assertEqual(r.wheel_url, "u1")


# ---------------------------------------------------------------------------
# parse_wheel_metadata + parse_requirement
# ---------------------------------------------------------------------------

class MetadataParse(unittest.TestCase):

    def test_extract_requires_dist(self):
        raw = (
            b"Metadata-Version: 2.1\n"
            b"Name: requests\n"
            b"Version: 2.31.0\n"
            b"Requires-Dist: charset-normalizer <4,>=2\n"
            b"Requires-Dist: idna <4,>=2.5\n"
            b"Requires-Dist: urllib3 <3,>=1.21.1\n"
            b"Requires-Dist: certifi >=2017.4.17\n"
            b"Requires-Dist: PySocks !=1.5.7,>=1.5.6 ; extra == 'socks'\n"
            b"\n"
            b"UNKNOWN\n"
        )
        reqs = resolver.parse_wheel_metadata(raw)
        self.assertEqual(len(reqs), 5)
        self.assertIn("charset-normalizer <4,>=2", reqs)

    def test_stops_at_body(self):
        raw = (
            b"Name: foo\n"
            b"Requires-Dist: a\n"
            b"\n"
            b"Requires-Dist: b\n"  # in body, must be ignored
        )
        reqs = resolver.parse_wheel_metadata(raw)
        self.assertEqual(reqs, ["a"])


class RequirementParse(unittest.TestCase):

    def test_plain_name(self):
        self.assertEqual(resolver.parse_requirement("requests"),
                         ("requests", "", ""))

    def test_name_with_specifier(self):
        self.assertEqual(resolver.parse_requirement("urllib3 <3,>=1.21.1"),
                         ("urllib3", "<3,>=1.21.1", ""))

    def test_name_with_extras_and_marker(self):
        n, s, m = resolver.parse_requirement(
            "PySocks[socks] !=1.5.7,>=1.5.6 ; extra == 'socks'"
        )
        self.assertEqual(n, "PySocks")
        self.assertEqual(s, "!=1.5.7,>=1.5.6")
        self.assertEqual(m, "extra == 'socks'")

    def test_optional_marker_detection(self):
        self.assertTrue(resolver.requirement_is_optional(
            "extra == 'socks'"))
        self.assertTrue(resolver.requirement_is_optional(
            'sys_platform == "win32"'))
        self.assertFalse(resolver.requirement_is_optional(
            "python_version >= '3.7'"))
        self.assertFalse(resolver.requirement_is_optional(""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
