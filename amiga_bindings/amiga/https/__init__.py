"""amiga.https — HTTPS GET for OS4 via `openssl s_client` shell-out.

Works around task #94 (Python _ssl/_socket fd interop is broken).
The trick: OS4's `openssl s_client` from AmiSSL 5.27 handshakes fine
against real HTTPS servers. Piping our request through it via AmigaDOS
pipes (`|`) — not stdin redirect (`<`, which is broken) — gets a full
HTTP response back over TLS. We shell out, capture to a temp file,
parse.

Requires:
  DH1:openssl                (AmiSSL 5.27+ CLI, from /Users/chris/.cache/amissl/AmiSSL-5.27-OS4.lha)
  DH1:AmiSSL/Certs           (assign AmiSSL: DH1:AmiSSL; certs unpacked)
  T: writable                (RAM:T assign)
"""
from __future__ import annotations
import os
import time
from urllib.parse import urlparse


class HTTPSError(RuntimeError):
    pass


def fetch(url: str, method: str = "GET", body: bytes | None = None,
          headers: dict | None = None, timeout: int = 30,
          openssl_path: str = "DH1:openssl",
          capath: str = "DH1:AmiSSL/Certs",
          insecure: bool = False,
          req_file: str = "T:_ah_req",
          out_file: str = "T:_ah_body") -> tuple[int, dict, bytes]:
    """Fetch an HTTPS URL. Returns (status, headers, body).

    Only supports single request/response (Connection: close). No
    keep-alive, no redirects (follow yourself). No chunked-encoding
    parsing.
    """
    if body is not None and method not in ("POST", "PUT", "PATCH"):
        raise ValueError(f"body not valid for {method}")

    u = urlparse(url)
    if u.scheme != "https":
        raise ValueError("only https:// URLs")
    host = u.hostname
    if not host:
        raise ValueError("no host in URL")
    port = u.port or 443
    path = (u.path or "/") + (("?" + u.query) if u.query else "")

    hdrs = {
        "Host": host,
        "User-Agent": "amiga.https/1.0",
        "Accept": "*/*",
        "Connection": "close",
    }
    if headers:
        hdrs.update(headers)
    if body is not None:
        hdrs["Content-Length"] = str(len(body))

    request_lines = [f"{method} {path} HTTP/1.0"]
    for k, v in hdrs.items():
        request_lines.append(f"{k}: {v}")
    request = ("\r\n".join(request_lines) + "\r\n\r\n").encode()
    if body is not None:
        request += body

    with open(req_file, "wb") as f:
        f.write(request)

    verify_arg = "" if insecure else f" -CApath {capath}"
    verify_flag = "" if insecure else ""

    # AmigaDOS pipe. `<file` doesn't feed s_client stdin; `type | prog`
    # does. -quiet suppresses the verify-info preamble so stdout is
    # only the HTTP response.
    cmd = (f"type {req_file} | {openssl_path} s_client "
           f"-connect {host}:{port} -servername {host} "
           f"-quiet{verify_arg} >{out_file}")

    rc = os.system(cmd)

    try:
        with open(out_file, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise HTTPSError(f"could not read response: {e}") from e

    # Try to strip openssl's own diagnostic lines (verify info, error
    # tail) that leak past -quiet on some versions. HTTP response
    # starts with 'HTTP/'.
    idx = raw.find(b"HTTP/")
    if idx < 0:
        raise HTTPSError(f"no HTTP/ marker in openssl output "
                          f"(rc={rc}): {raw[:400]!r}")
    raw = raw[idx:]

    # Split headers/body at CRLFCRLF.
    hdr_end = raw.find(b"\r\n\r\n")
    if hdr_end < 0:
        raise HTTPSError(f"malformed response (no header terminator): "
                          f"{raw[:200]!r}")
    header_block = raw[:hdr_end].decode("iso-8859-1", errors="replace")
    body_bytes = raw[hdr_end + 4:]
    # Trim trailing openssl error tail if any (starts with hex+":error:")
    err_marker = body_bytes.rfind(b":error:")
    if err_marker > 0:
        # Walk back to line start.
        cut = body_bytes.rfind(b"\n", 0, err_marker)
        if cut >= 0:
            body_bytes = body_bytes[:cut]

    status_line, _, rest_hdrs = header_block.partition("\r\n")
    parts = status_line.split(" ", 2)
    status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 0
    resp_headers: dict[str, str] = {}
    for line in rest_hdrs.split("\r\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            resp_headers[k.strip().lower()] = v.strip()

    # Prefer Content-Length to bound the body — openssl s_client can
    # spew a "Connecting to ...", cert-chain "depth=N ..." lines to
    # the same stdout AFTER the response completes even with -quiet.
    # Without CL truncation these leak into the body.
    cl_raw = resp_headers.get("content-length")
    if cl_raw and cl_raw.isdigit():
        cl = int(cl_raw)
        if cl <= len(body_bytes):
            body_bytes = body_bytes[:cl]

    return status, resp_headers, body_bytes


def get(url: str, **kw) -> tuple[int, dict, bytes]:
    return fetch(url, "GET", **kw)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("usage: python amiga_https.py <url>")
        sys.exit(1)
    st, h, b = get(sys.argv[1], insecure=("-insecure" in sys.argv))
    print(f"status: {st}")
    for k, v in h.items():
        print(f"  {k}: {v}")
    print(f"body: {len(b)} bytes")
    print(b[:600].decode("iso-8859-1", errors="replace"))
