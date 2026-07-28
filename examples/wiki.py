"""wiki.py — Wikipedia article summary lookup via the REST API.

HTTPS to en.wikipedia.org/api/rest_v1/page/summary/<title>. Prints
the extract, a couple of related-links, and the URL. Small enough
to render nicely in a terminal.

Usage:
    python3 python3:examples/wiki.py Amiga
    python3 python3:examples/wiki.py "Alan Turing"
    python3 python3:examples/wiki.py python (programming language)
"""
import sys, os, json, textwrap
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)


def pct_encode(s):
    """Minimal percent-encoding for URL path (spaces + a few reserved)."""
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-._~":
            out.append(ch)
        elif ch == " ":
            out.append("_")   # wikipedia convention
        else:
            out.append("%{:02X}".format(ord(ch.encode("utf-8")[0])
                                        if isinstance(ch, str)
                                        else ch))
    return "".join(out)


def fetch(title):
    from amiga import https as ah
    path = pct_encode(title)
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{path}"
    status, hdrs, body = ah.get(url, timeout=30)
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {body[:200]!r}")
    return json.loads(body)


def show(data):
    print(f"\n{data.get('title', '?')}")
    print("=" * min(70, len(data.get("title", ""))))
    desc = data.get("description")
    if desc:
        print(desc)
        print()
    extract = data.get("extract", "").strip()
    if extract:
        wrapped = textwrap.fill(extract, width=76, replace_whitespace=False)
        print(wrapped)
    print()
    urls = data.get("content_urls", {}).get("desktop", {})
    if "page" in urls:
        print(f"→ {urls['page']}")


def main():
    if len(sys.argv) < 2:
        print("usage: wiki.py <article title>", file=sys.stderr)
        sys.exit(2)
    title = " ".join(sys.argv[1:])
    print(f"wiki: looking up {title!r} ...", flush=True)
    data = fetch(title)
    if data is None:
        print(f"wiki: no article found for {title!r}", file=sys.stderr)
        sys.exit(1)
    show(data)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
