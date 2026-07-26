#!/usr/bin/env python3
"""browser.py — split-pane HTTP + RSS reader in Python for AmigaOS 4.

Left pane:  bookmarks / feed entries.
Right pane: fetched content — HTML stripped down to text, RSS parsed
            to item titles + links.
Top bar:    URL entry (via Fetch button → composite dialog) + a
            history dropdown-style list.
Bottom bar: Fetch / Home / Add Bookmark / Reload / Quit.

Runs entirely on the Amiga using the port's static-linked stdlib
(urllib.request, html.parser, xml.etree).  IPv4 only — we disabled
IPv6 at configure time.

Content rendering is deliberately minimalist — no images, no CSS.
The goal is to show that a real HTTP client + parser stack runs on
sam460ex/newlib, driving a real Intuition window.
"""
import io
import sys
import time

sys.path.insert(0, "DH1:pytests/amiga_bindings")

import _amiga
from amiga.ui import (App, Button, Label, ListPanel, Rect,
                       PEN_FG, PEN_BG, PEN_HI, PEN_ACC)


# ---------------------------------------------------------------------------
# Lazy imports — urllib pulls in hashlib.sha512 (missing from our build)
# via http.client's digest-auth path.  Deferring the import means the app
# still launches even when the network stack is unavailable; if the user
# actually tries to fetch, we surface a clean error in the transcript
# instead of dying with a top-level traceback at process startup.
# ---------------------------------------------------------------------------

_lazy_imports_done = False
_lazy_error = None
urllib_request = None
urllib_error   = None
HTMLParser     = None
ET             = None


def _lazy_imports():
    global _lazy_imports_done, _lazy_error
    global urllib_request, urllib_error, HTMLParser, ET
    if _lazy_imports_done:
        return _lazy_error is None
    _lazy_imports_done = True
    try:
        import urllib.request as _ur
        import urllib.error   as _ue
        from html.parser import HTMLParser as _HP
        from xml.etree import ElementTree as _ET
        urllib_request = _ur
        urllib_error   = _ue
        HTMLParser     = _HP
        ET             = _ET
        return True
    except Exception as e:
        import traceback
        _lazy_error = f"{type(e).__name__}: {e}"
        # capture traceback for debug view
        try:
            with open("T:browser_import_err.log", "w") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
        return False


BOOKMARKS = [
    "http://example.com/",
    "http://info.cern.ch/",
    "http://textfiles.com/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.reddit.com/r/amiga/.rss",
    "http://neverssl.com/",
]


# ---------------------------------------------------------------------------
# Fetch + parse
# ---------------------------------------------------------------------------

def fetch(url, timeout=15):
    req = urllib_request.Request(url, headers={
        "User-Agent": "AmigaPython/3.12 (compatible; sam460ex)",
    })
    try:
        with urllib_request.urlopen(req, timeout=timeout) as r:
            ct = r.headers.get_content_type()
            body = r.read()
        return ct, body
    except urllib_error.HTTPError as e:
        return "text/plain", f"HTTP error {e.code}: {e.reason}".encode()
    except urllib_error.URLError as e:
        return "text/plain", f"URL error: {e.reason}".encode()
    except Exception as e:
        return "text/plain", f"error: {e.__class__.__name__}: {e}".encode()


def _make_text_only():
    """Return a fresh HTMLParser subclass instance — done lazily so
    the class body doesn't run at module-import (HTMLParser may
    still be None then)."""
    class _TextOnly(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.buf = io.StringIO()
            self._skip = 0
            self._current_link = None

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self._skip += 1
            if tag == "a":
                a = dict(attrs)
                self._current_link = a.get("href")
            if tag in ("br", "p", "li", "tr", "h1", "h2", "h3", "h4"):
                self.buf.write("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self._skip:
                self._skip -= 1
            if tag == "a":
                if self._current_link:
                    self.buf.write(f" <{self._current_link}>")
                self._current_link = None
            if tag in ("p", "li", "tr", "h1", "h2", "h3", "h4"):
                self.buf.write("\n")

        def handle_data(self, data):
            if self._skip:
                return
            self.buf.write(" ".join(data.split()) + " ")
    return _TextOnly()


def render_html(body_bytes):
    try:
        text = body_bytes.decode("utf-8", errors="replace")
    except Exception:
        text = body_bytes.decode("latin-1", errors="replace")
    p = _make_text_only()
    try:
        p.feed(text)
    except Exception as e:
        return f"[html parser error: {e}]\n\n{text[:500]}"
    out = p.buf.getvalue()
    # collapse repeated blank lines
    lines = []
    prev_blank = False
    for line in out.split("\n"):
        line = line.strip()
        blank = not line
        if blank and prev_blank:
            continue
        lines.append(line)
        prev_blank = blank
    return "\n".join(lines).strip()


def render_rss(body_bytes):
    try:
        root = ET.fromstring(body_bytes)
    except ET.ParseError as e:
        return f"[xml parse error: {e}]"

    # Try RSS 2.0 (rss > channel > item) then Atom (feed > entry).
    items = []
    channel = root.find("channel")
    if channel is not None:
        for it in channel.findall("item"):
            items.append({
                "title": _t(it, "title"),
                "link":  _t(it, "link"),
                "date":  _t(it, "pubDate") or _t(it, "dc:date"),
                "descr": _t(it, "description"),
            })
    else:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for it in root.findall("a:entry", ns):
            link = it.find("a:link", ns)
            items.append({
                "title": _t(it, "a:title", ns),
                "link":  (link.get("href") if link is not None else ""),
                "date":  _t(it, "a:updated", ns) or _t(it, "a:published", ns),
                "descr": _t(it, "a:summary", ns) or _t(it, "a:content", ns),
            })

    if not items:
        return "[no <item>/<entry> children found — not RSS/Atom?]"
    out = io.StringIO()
    for i, item in enumerate(items[:30], 1):
        out.write(f"{i:>2d}. {item['title']}\n")
        if item.get("date"):  out.write(f"    {item['date']}\n")
        if item.get("link"):  out.write(f"    {item['link']}\n")
        if item.get("descr"):
            d = item["descr"]
            if len(d) > 200: d = d[:197] + "..."
            out.write(f"    {d}\n")
        out.write("\n")
    return out.getvalue()


def _t(elem, tag, ns=None):
    if ns:
        e = elem.find(tag, ns)
    else:
        e = elem.find(tag)
    if e is None or e.text is None:
        return ""
    return e.text.strip()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def do_fetch(app, url):
    if not _lazy_imports():
        app.state["msg"] = (f"network stack unavailable: {_lazy_error} "
                            "(see T:browser_import_err.log)")
        return
    app.state["msg"] = f"fetching {url} ..."
    app.request_redraw()   # let user see the status update before the block
    ct, body = fetch(url)
    if "xml" in ct or url.endswith((".rss", ".atom")) or "rss" in url:
        body_txt = render_rss(body)
    elif "html" in ct:
        body_txt = render_html(body)
    else:
        try:
            body_txt = body.decode("utf-8", errors="replace")
        except Exception:
            body_txt = f"[{len(body)} bytes of {ct}]"
    app.state["url"] = url
    app.state["body"] = body_txt
    app.state["ctype"] = ct
    if url not in app.state["history"]:
        app.state["history"].insert(0, url)
    app.state["msg"] = f"OK ({ct}, {len(body)} bytes)"


def on_pick_bookmark(app, idx, item):
    do_fetch(app, item)


def act_fetch(app):
    if not hasattr(_amiga, "open_dialog"):
        app.state["msg"] = "need _amiga.open_dialog for URL entry"; return
    h = _amiga.open_dialog(title="Fetch URL",
                            fields=[("url", app.state.get("url", "http://"), 250)],
                            ok_label="Go", cancel_label="Cancel",
                            left=180, top=140)
    try:
        r = _amiga.run_dialog(h)
    finally:
        _amiga.close_dialog(h)
    if not r or not r.get("url", "").strip():
        app.state["msg"] = "cancelled"; return
    do_fetch(app, r["url"].strip())


def act_home(app):
    do_fetch(app, BOOKMARKS[0])


def act_reload(app):
    if app.state.get("url"):
        do_fetch(app, app.state["url"])
    else:
        app.state["msg"] = "nothing to reload"


def act_add(app):
    if app.state.get("url") and app.state["url"] not in BOOKMARKS:
        BOOKMARKS.append(app.state["url"])
        app.state["list"].items = list(BOOKMARKS)
        app.state["msg"] = f"bookmarked {app.state['url']}"


def act_quit(app):
    app.stop()


# ---------------------------------------------------------------------------
# Draw the body pane
# ---------------------------------------------------------------------------

BODY_X0 = 260; BODY_X1 = 800; BODY_Y0 = 20; BODY_Y1 = 340
LINE_H = 12


def draw_body(app):
    app.fill(BODY_X0, BODY_Y0, BODY_X1, BODY_Y1, PEN_BG)
    for a, b, c, d in [(BODY_X0, BODY_Y0, BODY_X1, BODY_Y0),
                        (BODY_X0, BODY_Y1, BODY_X1, BODY_Y1),
                        (BODY_X0, BODY_Y0, BODY_X0, BODY_Y1),
                        (BODY_X1, BODY_Y0, BODY_X1, BODY_Y1)]:
        app.line(a, b, c, d, PEN_FG)

    url = app.state.get("url", "(nothing fetched yet)")
    app.text(BODY_X0 + 8, BODY_Y0 + 14, url[:60], PEN_ACC)
    ctype = app.state.get("ctype", "")
    if ctype:
        app.text(BODY_X0 + 8, BODY_Y0 + 30, f"content-type: {ctype}", PEN_FG)

    body = app.state.get("body", "")
    max_chars = (BODY_X1 - BODY_X0 - 20) // 8
    y = BODY_Y0 + 48
    top_line = app.state.get("scroll", 0)
    lines = body.splitlines()[top_line:]
    for line in lines:
        while line:
            chunk = line[:max_chars]
            app.text(BODY_X0 + 8, y, chunk, PEN_FG)
            y += LINE_H
            line = line[max_chars:]
            if y > BODY_Y1 - 6:
                return
        y += 2


def draw_status(app):
    app.fill(4, 388, 816, 404, PEN_BG)
    app.text(8, 400, app.state.get("msg", ""), PEN_HI)


def main():
    app = App(title="Python Browser", w=820, h=440, left=40, top=30)

    lst = ListPanel(rect=Rect(8, 20, 250, 340),
                     items=list(BOOKMARKS),
                     on_pick=on_pick_bookmark,
                     row_h=13)
    app.state["list"] = lst
    app.state["history"] = []
    app.state["msg"] = "click a bookmark on the left, or Fetch a URL below"
    app.state["scroll"] = 0

    y0, y1 = 350, 380
    W = 92
    def _btn(x, label, fn):
        return Button(Rect(x, y0, x + W, y1), label, on_click=fn)
    buttons = [
        _btn(  8, "Fetch",     act_fetch),
        _btn(104, "Home",      act_home),
        _btn(200, "Reload",    act_reload),
        _btn(296, "Bookmark",  act_add),
        _btn(392, "Scroll",    lambda a: a.state.update(scroll=a.state.get("scroll", 0) + 20)),
        _btn(488, "Top",       lambda a: a.state.update(scroll=0)),
        _btn(724, "Quit",      act_quit),
    ]

    app.widgets = [Label(8, 4, "Bookmarks", PEN_HI), lst, *buttons]

    def redraw(a):
        a.clear(PEN_BG)
        a.draw_widgets()
        draw_body(a)
        draw_status(a)

    def on_key(a, ch, code):
        if ch == "q": act_quit(a); return True
        if ch == "f": act_fetch(a); return True
        if ch == "r": act_reload(a); return True
        if ch == "h": act_home(a); return True
        if ch == " ":
            a.state["scroll"] = a.state.get("scroll", 0) + 20; return True
        if ch == "t":
            a.state["scroll"] = 0; return True
        return False

    app.redraw = redraw
    app.on_key = on_key
    app.run()


if __name__ == "__main__":
    main()
