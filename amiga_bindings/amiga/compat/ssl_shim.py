"""ssl_shim — stdlib `ssl` module replacement that routes HTTPS
through amiga.https (which shells out to the standalone `openssl`
binary at DH1:openssl).

Deployment: copy this file to `DH1:lib/ssl.py` so that
`import ssl` finds it before the stdlib. This only works when there
is no compiled `_ssl` builtin — i.e. the clib4 build of python-os4.
On the newlib build a compiled `_ssl` module wins the import; use
`from amiga.compat import ssl_shim; ssl_shim.install(force=True)` to
opt in at runtime.

What works
----------
- `import ssl` succeeds — provides all the constants and classes
  third-party introspection code checks.
- `ssl.create_default_context()` returns a stub `SSLContext`.
- Certificate loading (`load_verify_locations`, `load_cert_chain`,
  `load_default_certs`) — no-ops. Certs are handled by openssl at
  fetch time.
- `urllib.request.urlopen("https://…")` — transparently uses
  amiga.https via the monkey-patched `http.client.HTTPSConnection`.
- `http.client.HTTPSConnection(host).request()` / `.getresponse()`
  — same.

What does NOT work
------------------
- `ssl.SSLContext.wrap_socket(sock)` — cannot upgrade a live socket
  to TLS in-place with an external openssl binary. Raises
  `NotImplementedError` with a pointer to `amiga.https.fetch()`.
- Consequently: `requests`, `httpx`, `urllib3` — all upgrade a
  connected socket via `wrap_socket()`. They will fail with the
  above error. Use `amiga.https.fetch()` directly, or the
  monkey-patched `http.client.HTTPSConnection`.
- `imaplib.IMAP4_SSL` / `smtplib.SMTP_SSL` — same, they raw-wrap a
  socket. Not addressable without a real SSL library binding.
"""
from __future__ import annotations
import sys as _sys


# ─── constants: enum values third-party code may check ────────────────
# Protocol
PROTOCOL_TLS         = 2
PROTOCOL_TLS_CLIENT  = 16
PROTOCOL_TLS_SERVER  = 17
PROTOCOL_SSLv23      = PROTOCOL_TLS
PROTOCOL_TLSv1       = 3
PROTOCOL_TLSv1_1     = 4
PROTOCOL_TLSv1_2     = 5
PROTOCOL_TLSv1_3     = 6

# Verify modes
CERT_NONE     = 0
CERT_OPTIONAL = 1
CERT_REQUIRED = 2

# Verify flags
VERIFY_DEFAULT           = 0
VERIFY_CRL_CHECK_LEAF    = 4
VERIFY_CRL_CHECK_CHAIN   = 12
VERIFY_X509_STRICT       = 32
VERIFY_X509_TRUSTED_FIRST = 0x8000
VERIFY_ALLOW_PROXY_CERTS = 64
VERIFY_X509_PARTIAL_CHAIN = 0x80000

# SSL options
OP_ALL                 = 0x80000BFF
OP_NO_SSLv2            = 0x01000000
OP_NO_SSLv3            = 0x02000000
OP_NO_TLSv1            = 0x04000000
OP_NO_TLSv1_1          = 0x10000000
OP_NO_TLSv1_2          = 0x08000000
OP_NO_TLSv1_3          = 0x20000000
OP_NO_COMPRESSION      = 0x00020000
OP_NO_TICKET           = 0x00004000
OP_NO_RENEGOTIATION    = 0x40000000
OP_ENABLE_MIDDLEBOX_COMPAT = 0x00100000
OP_SINGLE_DH_USE       = 0x00100000
OP_SINGLE_ECDH_USE     = 0x00080000
OP_CIPHER_SERVER_PREFERENCE = 0x00400000
OP_ENABLE_KTLS         = 0x00000008

# Feature detection flags — third-party code checks these
HAS_SNI          = True
HAS_ECDH         = True
HAS_TLSv1_3      = True
HAS_ALPN         = False
HAS_NPN          = False
HAS_TLS_UNIQUE   = False
HAS_PHA          = False
HAS_PSK          = False
HAS_NEVER_CHECK_COMMON_NAME = False

# TLS version enum (introduced 3.7+)
class TLSVersion:
    MINIMUM_SUPPORTED = -2
    SSLv3     = 768
    TLSv1     = 769
    TLSv1_1   = 770
    TLSv1_2   = 771
    TLSv1_3   = 772
    MAXIMUM_SUPPORTED = -1


# Purposes (create_default_context arg)
class Purpose:
    SERVER_AUTH = _sys.intern("SERVER_AUTH")
    CLIENT_AUTH = _sys.intern("CLIENT_AUTH")


# OpenSSL version reporting — pretend to be a modern AmiSSL install
OPENSSL_VERSION        = "AmiSSL 5.27 via amiga.https shim"
OPENSSL_VERSION_INFO   = (3, 0, 12, 0, 0)
OPENSSL_VERSION_NUMBER = 0x300000c0


# ─── exception hierarchy ───────────────────────────────────────────────
class SSLError(OSError):
    """Raised by ssl-shim operations. Matches stdlib ssl.SSLError."""
    pass


class SSLZeroReturnError(SSLError):
    pass


class SSLWantReadError(SSLError):
    pass


class SSLWantWriteError(SSLError):
    pass


class SSLSyscallError(SSLError):
    pass


class SSLEOFError(SSLError):
    pass


class SSLCertVerificationError(SSLError, ValueError):
    verify_code = 0
    verify_message = ""


# Third-party code often catches CertificateError as an alias
CertificateError = SSLCertVerificationError


# ─── SSLContext stub ───────────────────────────────────────────────────
class SSLContext:
    """Stub SSLContext — accepts the standard configuration methods as
    no-ops, then rejects wrap_socket with a helpful message.

    All cert loading is silently accepted; the actual cert validation
    happens inside openssl at fetch time via -CApath."""
    def __init__(self, protocol=PROTOCOL_TLS_CLIENT):
        self.protocol = protocol
        self.verify_mode = CERT_REQUIRED if protocol == PROTOCOL_TLS_CLIENT else CERT_NONE
        self.check_hostname = protocol == PROTOCOL_TLS_CLIENT
        self.options = OP_ALL | OP_NO_SSLv2 | OP_NO_SSLv3
        self.verify_flags = VERIFY_DEFAULT
        self.minimum_version = TLSVersion.TLSv1_2
        self.maximum_version = TLSVersion.MAXIMUM_SUPPORTED
        self.hostname_checks_common_name = False
        self.post_handshake_auth = False
        self.security_level = 2

    # ---- cert config: no-op, retained for API completeness ----
    def load_verify_locations(self, cafile=None, capath=None, cadata=None):
        pass

    def load_cert_chain(self, certfile, keyfile=None, password=None):
        pass

    def load_default_certs(self, purpose=Purpose.SERVER_AUTH):
        pass

    def set_default_verify_paths(self):
        pass

    def set_ciphers(self, ciphers):
        pass

    def get_ciphers(self):
        return []

    def set_alpn_protocols(self, protocols):
        pass

    def set_ecdh_curve(self, curve_name):
        pass

    def set_servername_callback(self, callback):
        pass

    def cert_store_stats(self):
        return {"x509": 0, "crl": 0, "x509_ca": 0}

    def get_ca_certs(self, binary_form=False):
        return []

    # ---- the operations we can't fake ----
    def wrap_socket(self, sock, server_side=False,
                    do_handshake_on_connect=True,
                    suppress_ragged_eofs=True,
                    server_hostname=None, session=None):
        raise NotImplementedError(
            "amiga.compat.ssl_shim: SSLContext.wrap_socket cannot "
            "upgrade a live socket to TLS on this build (no linked "
            "SSL library). Use amiga.https.fetch(url) directly, or "
            "urllib.request.urlopen()/http.client.HTTPSConnection() "
            "which are transparently routed through amiga.https."
        )

    def wrap_bio(self, incoming, outgoing, server_side=False,
                 server_hostname=None):
        raise NotImplementedError(
            "amiga.compat.ssl_shim: wrap_bio (in-memory TLS) not "
            "supported without a linked SSL library."
        )


# ─── module-level helpers ───────────────────────────────────────────────
def create_default_context(purpose=Purpose.SERVER_AUTH, *,
                            cafile=None, capath=None, cadata=None):
    ctx = SSLContext(PROTOCOL_TLS_CLIENT
                     if purpose == Purpose.SERVER_AUTH
                     else PROTOCOL_TLS_SERVER)
    if cafile or capath or cadata:
        ctx.load_verify_locations(cafile, capath, cadata)
    return ctx


def _create_unverified_context(*args, **kwargs):
    ctx = create_default_context(*args, **kwargs)
    ctx.check_hostname = False
    ctx.verify_mode = CERT_NONE
    return ctx


# Both spellings — stdlib exports both
_create_default_https_context = create_default_context


def get_default_verify_paths():
    """Return the default OpenSSL cert paths. Points at AmiSSL's
    standard cert bundle on OS4."""
    from collections import namedtuple
    P = namedtuple("DefaultVerifyPaths",
                    ["cafile", "openssl_cafile_env", "openssl_cafile",
                     "capath", "openssl_capath_env", "openssl_capath"])
    return P(None, "SSL_CERT_FILE", None,
             "DH1:AmiSSL/Certs", "SSL_CERT_DIR", "DH1:AmiSSL/Certs")


def wrap_socket(sock, keyfile=None, certfile=None, server_side=False,
                cert_reqs=CERT_NONE, ssl_version=PROTOCOL_TLS,
                ca_certs=None, do_handshake_on_connect=True,
                suppress_ragged_eofs=True, ciphers=None):
    """Deprecated stdlib API. Not supported — see SSLContext.wrap_socket."""
    raise NotImplementedError(
        "amiga.compat.ssl_shim: ssl.wrap_socket() cannot upgrade a live "
        "socket. Use amiga.https.fetch(url) for HTTPS."
    )


def get_server_certificate(addr, ssl_version=PROTOCOL_TLS, ca_certs=None,
                           timeout=30):
    """Shell out to `openssl s_client -showcerts` to fetch the peer cert.
    Returns PEM-encoded string. Only supports the (host, port) tuple form."""
    import os as _os
    host, port = addr
    out_file = "T:_ssl_shim_cert"
    try: _os.remove(out_file)
    except OSError: pass
    cmd = (f"echo Q | DH1:openssl s_client -connect {host}:{port} "
           f"-servername {host} -showcerts -quiet >{out_file} 2>NIL:")
    _os.system(cmd)
    try:
        with open(out_file, "rb") as f:
            raw = f.read().decode("latin-1", errors="replace")
    except OSError as e:
        raise SSLError(f"openssl s_client failed: {e}") from e
    finally:
        try: _os.remove(out_file)
        except OSError: pass
    # Extract first PEM block
    begin = raw.find("-----BEGIN CERTIFICATE-----")
    end = raw.find("-----END CERTIFICATE-----", begin)
    if begin < 0 or end < 0:
        raise SSLError("no certificate returned by openssl s_client")
    return raw[begin:end + len("-----END CERTIFICATE-----")]


def PEM_cert_to_DER_cert(pem_cert_string):
    import base64
    parts = pem_cert_string.strip().split("-----")
    if len(parts) < 5:
        raise ValueError("invalid PEM")
    return base64.b64decode(parts[2].strip())


def DER_cert_to_PEM_cert(der_cert_bytes):
    import base64
    b64 = base64.encodebytes(der_cert_bytes).decode("ascii")
    return "-----BEGIN CERTIFICATE-----\n" + b64 + "-----END CERTIFICATE-----\n"


def cert_time_to_seconds(cert_time):
    """Convert stringified cert time (RFC 5280 or similar) to POSIX sec.
    Best-effort implementation using time.strptime."""
    import time as _time, calendar as _calendar
    # Format: "Jun  1 12:00:00 2020 GMT"
    return _calendar.timegm(_time.strptime(cert_time, "%b %d %H:%M:%S %Y %Z"))


# ─── http.client HTTPS monkey-patch ─────────────────────────────────────
def install(force=False):
    """Monkey-patch http.client.HTTPSConnection so its request/
    getresponse route through amiga.https instead of stdlib _ssl.

    Idempotent. Called automatically at module bottom unless
    `AMIGA_SSL_SHIM_NO_INSTALL` env var is set."""
    import http.client as _hc
    if getattr(_hc.HTTPSConnection, "_amiga_shim_installed", False) and not force:
        return
    try:
        from amiga.https import fetch as _amiga_fetch
    except ImportError:
        # amiga.https not on sys.path — nothing to patch to. This is
        # the case when the shim is imported outside the target guest
        # (e.g. host-side unit tests). Fail silently; wrap_socket
        # will still raise the helpful NotImplementedError.
        return

    from io import BytesIO
    import http.client as _hc_mod

    class _AmigaShimResponse:
        """http.client-compatible response wrapper around a
        (status, headers_dict, body_bytes) triple from amiga.https.
        Enough surface to satisfy urllib.request.HTTPResponse's
        expectations (code, msg, info(), etc.)."""
        def __init__(self, status, headers, body):
            self.status = int(status)
            # urllib.request checks response.code — legacy alias for status
            self.code = self.status
            self.reason = _hc_mod.responses.get(self.status, "Unknown")
            self.version = 11
            # urllib.request checks response.msg — the HTTPMessage
            self.msg = _hc_mod.HTTPMessage()
            for k, v in headers.items():
                self.msg[k] = v
            self.headers = self.msg
            self._body = body
            self._reader = BytesIO(body)
            self.closed = False
            self.will_close = True
            self.chunked = False
            self.chunk_left = None
            self.length = len(body)
            # urllib may check .url after the fact — provide a slot
            self.url = None

        def info(self):
            return self.msg

        def geturl(self):
            return self.url or ""

        def getcode(self):
            return self.status

        def read(self, amt=None):
            if amt is None:
                return self._reader.read()
            return self._reader.read(amt)

        def readinto(self, b):
            return self._reader.readinto(b)

        def readable(self):
            return not self.closed

        def readline(self, limit=-1):
            return self._reader.readline(limit)

        def isclosed(self):
            return self.closed

        def getheader(self, name, default=None):
            return self.msg.get(name, default)

        def getheaders(self):
            return list(self.msg.items())

        def fileno(self):
            raise OSError("amiga.compat.ssl_shim response has no underlying fd")

        def close(self):
            self.closed = True

        def flush(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    _orig_init = _hc_mod.HTTPSConnection.__init__

    def _shim_init(self, host, port=None, key_file=None, cert_file=None,
                    timeout=None, source_address=None, *,
                    context=None, check_hostname=None,
                    blocksize=8192):
        self.host = host
        self.port = port or 443
        self.timeout = timeout if timeout else 30
        self.source_address = source_address
        self.blocksize = blocksize
        self._method = None
        self._url = None
        self._headers = {}
        self._body = None
        self._context = context
        # Attributes http.client.HTTPResponse may check
        self.sock = None
        self._buffer = []
        self._HTTPConnection__state = "Idle"
        self._HTTPConnection__response = None

    def _shim_request(self, method, url, body=None, headers=None,
                      *, encode_chunked=False):
        self._method = method
        self._url = url
        # Preserve dict order; also normalize case-insensitive keys
        self._headers = dict(headers) if headers else {}
        if isinstance(body, str):
            body = body.encode("utf-8")
        self._body = body

    def _shim_getresponse(self):
        # Build the full URL from stored request state
        # Include :port only if non-default
        if self.port == 443:
            netloc = self.host
        else:
            netloc = f"{self.host}:{self.port}"
        full_url = f"https://{netloc}{self._url}"
        status, resp_headers, resp_body = _amiga_fetch(
            full_url,
            method=self._method or "GET",
            body=self._body,
            headers=self._headers,
            timeout=self.timeout or 30,
        )
        return _AmigaShimResponse(status, resp_headers, resp_body)

    def _shim_close(self):
        # Nothing to close; fetch is one-shot
        self._method = None
        self._url = None
        self._body = None

    def _shim_connect(self):
        # amiga.https opens its own connection per fetch — no-op here
        pass

    def _shim_send(self, data):
        # http.client sometimes calls send() directly (chunked/large).
        # For our shim, everything happens in fetch(). Accumulate.
        if isinstance(data, str):
            data = data.encode("utf-8")
        if self._body is None:
            self._body = data
        else:
            self._body += data

    def _shim_endheaders(self, message_body=None, *, encode_chunked=False):
        if message_body is not None:
            if isinstance(message_body, str):
                message_body = message_body.encode("utf-8")
            self._body = (self._body or b"") + message_body

    _hc_mod.HTTPSConnection.__init__ = _shim_init
    _hc_mod.HTTPSConnection.request = _shim_request
    _hc_mod.HTTPSConnection.getresponse = _shim_getresponse
    _hc_mod.HTTPSConnection.close = _shim_close
    _hc_mod.HTTPSConnection.connect = _shim_connect
    _hc_mod.HTTPSConnection.send = _shim_send
    _hc_mod.HTTPSConnection.endheaders = _shim_endheaders
    _hc_mod.HTTPSConnection._amiga_shim_installed = True


# ─── auto-install at import ─────────────────────────────────────────────
# Users can opt out by setting AMIGA_SSL_SHIM_NO_INSTALL in the
# environment before their program imports ssl.
import os as _os
if not _os.environ.get("AMIGA_SSL_SHIM_NO_INSTALL"):
    try:
        install()
    except BaseException:
        # If install fails for any reason, ssl still imports fine —
        # only the http.client transparent wiring is lost.
        pass
