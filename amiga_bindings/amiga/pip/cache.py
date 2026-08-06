"""amiga.pip.cache — content-addressed wheel cache.

Wheels are cached under a directory (default T:pip-cache) using their
PyPI-provided filename. Content is verified by SHA-256 from the JSON's
`digests.sha256` field before install — a mismatched or missing cache
entry gets re-downloaded.

`T:` is RAM-backed on OS4 so the cache is lost per reboot; move to
`DH1:pip-cache` for persistence.
"""
from __future__ import annotations
import hashlib
import os


DEFAULT_CACHE_DIR = "T:pip-cache"


def _mkdir_p(path):
    """os.makedirs(exist_ok=True) — works on OS4 AmigaDOS paths."""
    try:
        os.makedirs(path)
    except OSError:
        pass


def cache_path_for(url_or_filename, cache_dir=None):
    """Return the local path where the wheel with this filename would
    be cached. Accepts full URLs (uses the basename) or bare filenames."""
    if cache_dir is None:
        cache_dir = DEFAULT_CACHE_DIR
    _mkdir_p(cache_dir)
    name = os.path.basename(url_or_filename)
    return os.path.join(cache_dir, name)


def sha256_file(path, chunk_size=65536):
    """Streaming SHA-256 of a file. Returns hex digest."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk_size)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def verify(path, expected_sha256):
    """True if the file at `path` exists and matches expected_sha256.
    Empty expected_sha256 → skip verification, only check existence."""
    if not os.path.isfile(path):
        return False
    if not expected_sha256:
        return True
    actual = sha256_file(path)
    return actual.lower() == expected_sha256.lower()
