"""amiga.netfix — one-line workaround for the broken newlib DNS/resolver
on our OS4 Python build.

Symptoms on that build:
  * socket.gethostbyname("localhost")   -> OSError [Errno 78]
  * socket.getaddrinfo(host, port, ...) -> OSError [Errno 78] every variant
  * ...but socket.socket() + s.connect((ip, port)) works fine.

So the *raw connect* path in bsdsocket is healthy — only the resolver
entrypoints newlib exposes are broken.  This module patches
`socket.gethostbyname` and `socket.getaddrinfo` to:

  1. If the host is already a numeric IPv4 dotted-quad, skip the OS
     resolver entirely and hand back a synthetic addrinfo tuple.
  2. Otherwise shell out to the AmigaOS `ping` command (which uses
     Roadshow's own resolver + works correctly) to obtain the IP,
     cache it, and then return a synthetic addrinfo for that IP.

That's enough to make `urllib.request.urlopen()`, `http.client`,
`smtplib`, etc. work with hostname URLs.

Usage: at the top of your OS4 Python script, before importing
urllib / http / anything socket-using:

    import amiga.netfix    # noqa: install socket patches
"""
from __future__ import annotations

import os
import re
import socket

__all__ = ["install", "resolve", "cache"]

_NUMERIC_IPV4 = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_PING_LINE_RE = re.compile(r"\((\d+\.\d+\.\d+\.\d+)\)")
cache: dict[str, str | None] = {}    # host -> ip, or None if unresolvable


def resolve(host: str) -> str | None:
    """Return numeric IPv4 for `host` (which may already be numeric).
    Uses a per-process cache backed by AmigaOS `ping` for name lookup."""
    if not host:
        return None
    if _NUMERIC_IPV4.match(host):
        return host
    if host in cache:
        return cache[host]
    tmp = f"T:netfix_ping.{os.getpid()}"
    # `-c 1 -n` = one packet, don't reverse-lookup. OS4 ping doesn't
    # accept -q or -t so keep the arg list minimal.
    rc = os.system(f"ping -c 1 -n {host} >{tmp}")
    ip: str | None = None
    try:
        with open(tmp) as f:
            for line in f:
                m = _PING_LINE_RE.search(line)
                if m:
                    ip = m.group(1)
                    break
    except OSError:
        pass
    finally:
        try: os.remove(tmp)
        except OSError: pass
    cache[host] = ip
    return ip


def _synth_addrinfo(ip: str, port):
    """Return a getaddrinfo-shaped list for a single IPv4 address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "",
             (ip, port if port is not None else 0))]


def install() -> None:
    """Monkey-patch socket.gethostbyname + socket.getaddrinfo."""
    # gethostbyname
    def _gethostbyname(host: str) -> str:
        ip = resolve(host)
        if ip is None:
            raise socket.gaierror(-2, f"amiga.netfix: could not resolve {host!r}")
        return ip
    socket.gethostbyname = _gethostbyname

    # gethostbyname_ex
    def _gethostbyname_ex(host: str):
        ip = resolve(host)
        if ip is None:
            raise socket.gaierror(-2, f"amiga.netfix: could not resolve {host!r}")
        return (host, [], [ip])
    socket.gethostbyname_ex = _gethostbyname_ex

    # getaddrinfo — the one that unblocks urllib.
    def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        # None host => wildcard (bind to any).
        if host is None:
            host = "0.0.0.0"
        # Port may be a service name string. int() falls back to the
        # common well-known ports.
        if isinstance(port, str):
            svc_map = {"http": 80, "https": 443, "ftp": 21, "smtp": 25,
                        "pop3": 110, "imap": 143, "dns": 53}
            port = svc_map.get(port.lower(), 0) if not port.isdigit() else int(port)
        ip = resolve(host)
        if ip is None:
            raise socket.gaierror(-2, f"amiga.netfix: could not resolve {host!r}")
        return _synth_addrinfo(ip, port)
    socket.getaddrinfo = _getaddrinfo


# Install on import so callers only need `import amiga.netfix`.
install()
