"""amiga.pip.resolver — resolve a PyPI package to a pure-Python wheel URL.

Given a JSON blob from https://pypi.org/pypi/{name}/json (or the newer
https://pypi.org/pypi/{name}/{version}/json for a specific version), pick
the highest release with a `*-py3-none-any.whl` and return
(version, wheel_url, wheel_sha256, requires_dist).

Kept as a pure module: no I/O, no HTTPS. Feed it dict data; test offline.
"""
from __future__ import annotations
import re
from collections import namedtuple

ResolvedRelease = namedtuple(
    "ResolvedRelease", "name version wheel_url wheel_sha256 requires_dist"
)


class ResolveError(Exception):
    """No compatible pure-Python wheel available for this package."""


# ---------------------------------------------------------------------------
# Version parsing — enough of PEP 440 for our "pick highest stable" pass.
# Full spec is 39 KB in packaging/version.py; we cover the common cases.
# ---------------------------------------------------------------------------

_VER_RE = re.compile(
    r"^\s*v?"
    r"(?:(?P<epoch>\d+)!)?"                 # 1! epoch
    r"(?P<rel>\d+(?:\.\d+)*)"                # 1.2.3
    # pre-release marker — allow optional [._-] separator, e.g.
    # 1.0.pre1 or 1.0a1 both accepted. `dev` intentionally excluded
    # (has its own group so we can order it separately).
    r"(?P<pre>[._-]?(?:a|b|c|rc|alpha|beta|pre)(?:\.?\d+)?)?"
    r"(?P<post>\.post\d+)?"
    r"(?P<dev>\.dev\d+)?"
    r"(?:\+[a-zA-Z0-9.]+)?"                  # local segment
    r"\s*$"
)


_PRE_NAME_RANK = {
    "a": 1, "alpha": 1,
    "b": 2, "beta": 2,
    "c": 3, "rc": 3, "pre": 3,
}


def parse_version(s):
    """Parse a PEP 440-ish version to a sortable tuple.

    Sort order (from smallest = earliest to largest = latest):
        X.Y.Z.devN  <  X.Y.ZaN.devM  <  X.Y.ZaN  <
        X.Y.ZrcN    <  X.Y.Z         <  X.Y.Z.postN

    Encoded as (epoch, release_tuple, phase, post) where phase is
    (finalness, pre_rank, dev_num_or_MAX). `finalness` = 0 for anything
    with a pre or dev marker, 1 for a plain final/post release — so
    (1,…) sorts strictly after (0,…). Within finalness=0, we compare
    pre_rank (0 means "no pre marker" — dev-only sorts as if it were
    an alpha/pre-anything variant of the base version).
    """
    m = _VER_RE.match(s)
    if not m:
        # Unparseable — sort to the very bottom so we never pick it.
        return (-1, (0,), (-1, 0, 0), 0)

    epoch = int(m.group("epoch") or 0)
    rel = tuple(int(x) for x in m.group("rel").split("."))
    pre_marker = m.group("pre")
    dev_marker = m.group("dev")
    post_marker = m.group("post")

    if pre_marker:
        head = re.match(r"[._-]?([a-z]+)", pre_marker).group(1)
        pre_rank = _PRE_NAME_RANK.get(head, 4)
    else:
        pre_rank = 0

    dev_num = int(dev_marker[4:]) if dev_marker else None

    if pre_marker and dev_marker:
        phase = (0, pre_rank, dev_num)                # eg 1.0a1.dev5
    elif pre_marker:
        phase = (0, pre_rank, 10**9)                  # eg 1.0a1 (no dev)
    elif dev_marker:
        phase = (0, 0, dev_num)                       # eg 1.0.dev5
    else:
        phase = (1, 0, 0)                             # final release

    post_val = int(post_marker[5:]) if post_marker else 0
    return (epoch, rel, phase, post_val)


def is_pre_release(v):
    """True if the version has a pre-release or dev suffix — we skip
    these by default when picking 'the' latest wheel."""
    m = _VER_RE.match(v)
    if not m:
        return False
    return bool(m.group("pre") or m.group("dev"))


# ---------------------------------------------------------------------------
# Wheel-file inspection.
# Wheel filename spec (PEP 427):
#   {distribution}-{version}(-{build})?-{python}-{abi}-{platform}.whl
# We only accept py3-none-any (pure-Python universal).
# ---------------------------------------------------------------------------

def is_compatible_wheel(filename):
    """True for `*-py3-none-any.whl` and `*-py2.py3-none-any.whl`."""
    if not filename.endswith(".whl"):
        return False
    stem = filename[:-4]
    parts = stem.split("-")
    if len(parts) < 5:
        return False
    python_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
    if abi_tag != "none" or platform_tag != "any":
        return False
    # Accept 'py3', 'py2.py3', 'py30..39', 'cp3xx'-style is NOT acceptable
    # (we don't have those Python versions matching)
    if python_tag == "py3":
        return True
    if python_tag == "py2.py3":
        return True
    # Some old wheels use 'py3.11' style; accept if it contains 'py3'
    if "py3" in python_tag.split("."):
        return True
    return False


# ---------------------------------------------------------------------------
# Resolver: take a full PyPI JSON blob, return a ResolvedRelease.
# The JSON shape is documented at https://warehouse.pypa.io/api-reference/json.html.
# Relevant fields:
#   data["info"]["name"], ["requires_dist"] (list of PEP 508 strings)
#   data["releases"] = {version: [file_records]}
#     each file record has "filename", "url", "digests": {"sha256": ...},
#     "yanked", "packagetype" (wheel|bdist_wheel|sdist)
# ---------------------------------------------------------------------------

def resolve_from_json(data, prefer_version=None, allow_pre=False):
    """Given a parsed PyPI JSON, return a ResolvedRelease.

    prefer_version: exact version string; if set, only that release is
        considered.
    allow_pre: include pre/dev/rc releases in the candidate pool.

    Raises ResolveError with a diagnostic message on no match.
    """
    if not isinstance(data, dict) or "releases" not in data:
        raise ResolveError("PyPI JSON missing 'releases' key")
    name = (data.get("info") or {}).get("name") or "?"
    releases = data["releases"]

    candidates = []
    for version, files in releases.items():
        if prefer_version and version != prefer_version:
            continue
        if not allow_pre and is_pre_release(version) and not prefer_version:
            continue
        for f in files or ():
            if f.get("yanked"):
                continue
            fname = f.get("filename", "")
            if not is_compatible_wheel(fname):
                continue
            digest = (f.get("digests") or {}).get("sha256", "")
            candidates.append((parse_version(version), version, f["url"],
                               digest, fname))

    if not candidates:
        raise ResolveError(
            f"no py3-none-any wheel available for {name}"
            + (f" version {prefer_version}" if prefer_version else "")
        )
    candidates.sort(key=lambda c: c[0])
    _, chosen_version, wheel_url, sha256, chosen_fname = candidates[-1]

    # requires_dist may sit under top-level "info" (latest-release JSON)
    # or under the per-file record — top-level is what we care about
    # since we resolved for a specific version.
    reqs = _resolve_requires_dist(data, chosen_version)

    return ResolvedRelease(
        name=name,
        version=chosen_version,
        wheel_url=wheel_url,
        wheel_sha256=sha256,
        requires_dist=tuple(reqs or ()),
    )


def _resolve_requires_dist(data, chosen_version):
    """PyPI's JSON shape depends on which endpoint you hit:
      /pypi/{name}/json          → info.requires_dist is for the LATEST
                                    release, which may or may not be chosen
      /pypi/{name}/{ver}/json    → info.requires_dist is for {ver} directly
    We prefer the per-version endpoint, but fall back to top-level
    info if it happens to match.
    """
    info = data.get("info") or {}
    if info.get("version") == chosen_version:
        return info.get("requires_dist") or []
    # Fallback: return empty; caller will refetch per-version JSON if
    # they want authoritative deps.
    return []


# ---------------------------------------------------------------------------
# METADATA parsing — extract Requires-Dist entries from a wheel's METADATA
# file (used as fallback / cross-check against the PyPI JSON).
# ---------------------------------------------------------------------------

def parse_wheel_metadata(metadata_bytes):
    """Given the raw bytes of a wheel's METADATA file, return the list
    of Requires-Dist lines (as strings). Handles simple RFC-822 style."""
    text = metadata_bytes.decode("utf-8", errors="replace")
    lines = text.split("\n")
    out = []
    for line in lines:
        if line.startswith("Requires-Dist:"):
            out.append(line[len("Requires-Dist:"):].strip())
        elif not line.strip():
            break  # end of headers, before body
    return out


# ---------------------------------------------------------------------------
# Requirement string parsing — enough of PEP 508 to strip extras/markers
# and get a bare package name + optional version spec.
# ---------------------------------------------------------------------------

_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def parse_requirement(req):
    """Take a PEP 508 requirement string like
       'charset-normalizer<4,>=2 ; python_version >= "3.7" and extra == "socks"'
    Return (name, spec_str, marker_str) — spec + marker may be empty.

    We only care about the name for dep-walking. Spec is passed through
    so higher-level code can decide whether to enforce it (we don't).
    """
    if not isinstance(req, str):
        return ("", "", "")
    m = _REQ_NAME_RE.match(req)
    if not m:
        return ("", "", "")
    name = m.group(1)
    rest = req[m.end():].strip()
    marker = ""
    if ";" in rest:
        rest, marker = rest.split(";", 1)
        marker = marker.strip()
    # Strip [extras] if present
    if rest.startswith("["):
        end = rest.find("]")
        if end >= 0:
            rest = rest[end + 1:].strip()
    spec = rest.strip()
    return (name, spec, marker)


def requirement_is_optional(marker):
    """True if the marker says this dep is only needed under an extra
    (which we don't request) or on a platform we're not on. Best-effort;
    real PEP 508 marker evaluation is complex."""
    if not marker:
        return False
    m = marker.lower()
    # Any `extra == "foo"` marker → optional (we never request extras)
    if 'extra ==' in m or 'extra=="' in m or 'extra ==\'' in m:
        return True
    # sys_platform / os_name / platform_system markers targeting
    # things we're clearly not (win32, darwin, linux)
    for tag in ("win32", "cygwin", "darwin", "linux", "freebsd"):
        if f'"{tag}"' in m or f"'{tag}'" in m:
            return True
    return False
