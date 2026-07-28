"""rss_reader.py — fetch + display an Atom/RSS feed over HTTPS.

Uses amiga.https (openssl s_client shell-out) for the fetch and
xml.etree.ElementTree for parsing. Prints titles + links + short
descriptions. Interactive mode lets you press 'o' + a number to
open one article's URL in browser.py.

Default feed: BBC News world (RSS 2.0). Pass a URL on the command
line to fetch anything else:

    python3 python3:examples/rss_reader.py
    python3 python3:examples/rss_reader.py https://feeds.bbci.co.uk/news/world/rss.xml
"""
import sys
for _p in ("python3:amiga_bindings", "System/python3/amiga_bindings", os.path.join(os.path.dirname(__file__), "..", "amiga_bindings")):
    if os.path.exists(_p) and _p not in sys.path:
        sys.path.insert(0, _p)
sys.path.insert(0, "python3:examples")   # for browser.fetch


DEFAULT_FEED = "https://feeds.bbci.co.uk/news/world/rss.xml"


def fetch_feed(url):
    """HTTPS GET + return body bytes. HTTP too — falls through."""
    if url.lower().startswith("https://"):
        from amiga import https as ah
        status, hdrs, body = ah.get(url, timeout=30)
        if status != 200:
            raise RuntimeError(f"HTTP {status}: {body[:200]!r}")
        return body
    else:
        import urllib.request
        with urllib.request.urlopen(url, timeout=30) as r:
            return r.read()


def parse_feed(body):
    """Return list of dicts: [{title, link, summary}, ...].

    Handles both Atom (<entry><title/><link href/><summary/>) and
    RSS 2.0 (<item><title/><link/><description/>) — checks the root
    tag to pick the right XPath.
    """
    import xml.etree.ElementTree as ET
    root = ET.fromstring(body)
    tag = root.tag.split("}", 1)[-1]        # strip xmlns
    entries = []

    if tag == "rss":
        # RSS 2.0: /rss/channel/item/{title,link,description}
        for item in root.findall("./channel/item"):
            entries.append({
                "title":   (item.findtext("title") or "").strip(),
                "link":    (item.findtext("link")  or "").strip(),
                "summary": (item.findtext("description") or "").strip(),
            })
    elif tag == "feed":
        # Atom — namespaced.
        NS = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", NS):
            link_el = entry.find("a:link", NS)
            link = link_el.get("href", "") if link_el is not None else ""
            entries.append({
                "title":   (entry.findtext("a:title",   default="", namespaces=NS)).strip(),
                "link":    link,
                "summary": (entry.findtext("a:summary", default="", namespaces=NS)).strip(),
            })
    else:
        raise ValueError(f"unknown feed root tag: {tag}")

    return entries


def strip_html(s, maxlen=140):
    """Very rough HTML-strip for summary preview."""
    import re
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen] + ("..." if len(s) > maxlen else "")


def show(entries, limit=15):
    for i, e in enumerate(entries[:limit], 1):
        print(f"[{i:>2}] {e['title']}")
        print(f"     {e['link']}")
        if e["summary"]:
            print(f"     {strip_html(e['summary'])}")
        print()


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FEED
    print(f"rss_reader: fetching {url}", flush=True)
    body = fetch_feed(url)
    print(f"rss_reader: {len(body)} bytes fetched, parsing...", flush=True)
    entries = parse_feed(body)
    print(f"rss_reader: {len(entries)} entries\n", flush=True)
    show(entries)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
