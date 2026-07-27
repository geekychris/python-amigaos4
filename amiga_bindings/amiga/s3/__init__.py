"""amiga.s3 — pure-Python S3 / MinIO client for OS4.

Why hand-rolled: boto3 and minio both drive their HTTP through
urllib3, which hits task #94 (Python `_ssl` + `_socket` fd interop
is broken on OS4). Instead this module signs SigV4 in Python and
shells the request out through `amiga.https`, which uses AmiSSL's
`openssl s_client` and works today.

Supported verbs:
    list_buckets()
    list_objects(bucket, prefix="", max_keys=1000)
    get_object(bucket, key)
    put_object(bucket, key, data, content_type=...)
    stat_object(bucket, key)      # HEAD
    delete_object(bucket, key)

Not supported yet (add when needed):
    multipart uploads, presigned URLs, ACLs, versioning,
    chunked-transfer response bodies (`amiga.https` reads fixed CL only).

Addressing: path-style only. MinIO and modern AWS both accept
`https://<endpoint>/<bucket>/<key>` which avoids per-bucket DNS
lookups. Set `endpoint="s3.amazonaws.com"` for AWS proper.

Region defaults to "us-east-1" — override for other AWS regions.
"""
from __future__ import annotations

import datetime
import hashlib
import hmac
import re
import time
import urllib.parse

from amiga import https as _https

# S3 XML is simple, well-defined, and never has attributes or CDATA
# on the tags we care about. Python's xml.etree needs the `_expat` C
# extension, which our OS4 Python build doesn't have as a static
# builtin. Regex is enough for our shape.


def _xml_iter(body: bytes, tag: str):
    """Yield each <tag>...</tag> block. Namespace-blind (ignores any
    xmlns=... on the parent). Case-sensitive."""
    # Non-greedy so we don't accidentally span two blocks.
    pat = re.compile(rf"<{tag}\b[^>]*>(.*?)</{tag}>", re.DOTALL)
    text = body.decode("utf-8", errors="replace")
    for m in pat.finditer(text):
        yield m.group(1)


def _xml_field(block: str, tag: str) -> str:
    """Extract the text content of a single <tag>...</tag> inside a
    block. Empty string if missing. Strips & entities."""
    m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.DOTALL)
    if not m:
        return ""
    v = m.group(1)
    # S3 only ever uses these entities in error messages / metadata.
    return (v.replace("&amp;", "&")
             .replace("&lt;", "<")
             .replace("&gt;", ">")
             .replace("&quot;", '"')
             .replace("&#39;", "'"))


EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class S3Error(RuntimeError):
    """S3 returned a non-2xx response.

    Attributes: status, code (str, from <Error><Code>), message (from
    <Message>), body (raw XML bytes).
    """
    def __init__(self, status: int, code: str, message: str, body: bytes):
        super().__init__(f"S3 {status} {code}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.body = body


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _uri_encode(s: str, encode_slash: bool = True) -> str:
    """AWS SigV4 uri-encode. Unreserved chars stay; everything else
    becomes %XX (uppercase hex). Slash-encoding controlled explicitly:
    canonical URI keeps slashes, canonical query encodes them."""
    safe = "-._~"
    if not encode_slash:
        safe += "/"
    return urllib.parse.quote(s, safe=safe)


def _canonical_query(params: dict[str, str]) -> str:
    if not params:
        return ""
    parts = []
    for k in sorted(params):
        v = params[k]
        parts.append(f"{_uri_encode(k, True)}={_uri_encode(v, True)}")
    return "&".join(parts)


def _signing_key(secret: str, date_stamp: str, region: str,
                 service: str = "s3") -> bytes:
    k_date = _hmac(("AWS4" + secret).encode(), date_stamp)
    k_region = _hmac(k_date, region)
    k_service = _hmac(k_region, service)
    return _hmac(k_service, "aws4_request")


def _iso_now(fake_now: float | None = None) -> tuple[str, str]:
    """Return (amz_date, date_stamp).

    amz_date  = YYYYMMDDTHHMMSSZ  (goes in x-amz-date header)
    date_stamp = YYYYMMDD          (goes in credential scope)
    """
    if fake_now is None:
        t = time.gmtime()
    else:
        t = time.gmtime(fake_now)
    amz = time.strftime("%Y%m%dT%H%M%SZ", t)
    stamp = time.strftime("%Y%m%d", t)
    return amz, stamp


def _parse_error(status: int, body: bytes) -> S3Error:
    """S3 error bodies are <Error><Code>...</Code><Message>...</Message></Error>."""
    text = body.decode("utf-8", errors="replace")
    code = _xml_field(text, "Code")
    msg = _xml_field(text, "Message")
    if not code and not msg:
        msg = text[:200]
    return S3Error(status, code, msg, body)


class S3Client:
    """Minimal S3 client.

    endpoint:    hostname of the S3 service. e.g. "play.min.io" or
                 "s3.amazonaws.com". Do NOT include scheme.
    access_key:  AWS access key ID.
    secret_key:  AWS secret access key.
    region:      AWS region (default us-east-1).
    secure:      True for https:// (only mode supported — SigV4 is
                 fine over HTTP but amiga.https is HTTPS-only).
    """

    def __init__(self, endpoint: str, access_key: str, secret_key: str,
                 region: str = "us-east-1", secure: bool = True,
                 insecure_tls: bool = False):
        if not secure:
            raise ValueError("plain HTTP not supported (amiga.https is HTTPS-only)")
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        self.insecure_tls = insecure_tls

    # ------------------------------------------------------------------ signing

    def _sign(self, method: str, path: str, query: dict[str, str],
              body: bytes, extra_headers: dict[str, str] | None = None
              ) -> dict[str, str]:
        """Build all headers for a SigV4 request (host, x-amz-date,
        x-amz-content-sha256, authorization, + any extras).

        Returns the header dict ready to hand to amiga.https.fetch().
        """
        amz_date, date_stamp = _iso_now()
        payload_hash = _sha256_hex(body)

        headers: dict[str, str] = {
            "host": self.endpoint,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        if extra_headers:
            for k, v in extra_headers.items():
                headers[k.lower()] = v

        signed_names = sorted(headers)
        canon_headers = "".join(f"{k}:{headers[k].strip()}\n"
                                for k in signed_names)
        signed_header_list = ";".join(signed_names)

        canonical_uri = _uri_encode(path, encode_slash=False)
        canonical_query = _canonical_query(query)

        canonical_request = (
            f"{method}\n"
            f"{canonical_uri}\n"
            f"{canonical_query}\n"
            f"{canon_headers}\n"
            f"{signed_header_list}\n"
            f"{payload_hash}"
        )

        credential_scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = (
            f"AWS4-HMAC-SHA256\n"
            f"{amz_date}\n"
            f"{credential_scope}\n"
            f"{_sha256_hex(canonical_request.encode())}"
        )

        signing_key = _signing_key(self.secret_key, date_stamp, self.region)
        signature = hmac.new(signing_key, string_to_sign.encode(),
                             hashlib.sha256).hexdigest()

        authorization = (
            f"AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_header_list}, "
            f"Signature={signature}"
        )
        headers["authorization"] = authorization

        # amiga.https will inject its own Host and Content-Length —
        # remove our lowercase 'host' from the return set to avoid
        # dupes (it's already used for signing).
        out = dict(headers)
        del out["host"]
        return out

    def _request(self, method: str, path: str, query: dict[str, str] | None,
                 body: bytes, content_type: str | None = None
                 ) -> tuple[int, dict, bytes]:
        query = query or {}
        extra = {"Content-Type": content_type} if content_type else None
        headers = self._sign(method, path, query, body, extra)

        url = f"https://{self.endpoint}{_uri_encode(path, False)}"
        if query:
            url += "?" + _canonical_query(query)

        kw: dict = {"method": method, "headers": headers,
                    "insecure": self.insecure_tls}
        if body:
            kw["body"] = body
        elif method in ("POST", "PUT", "PATCH"):
            kw["body"] = b""

        return _https.fetch(url, **kw)

    # ------------------------------------------------------------------ verbs

    def list_buckets(self) -> list[dict]:
        """GET / — returns [{'name': str, 'creation_date': str}]."""
        st, _, body = self._request("GET", "/", None, b"")
        if st != 200:
            raise _parse_error(st, body)

        buckets = []
        for block in _xml_iter(body, "Bucket"):
            name = _xml_field(block, "Name")
            if name:
                buckets.append({
                    "name": name,
                    "creation_date": _xml_field(block, "CreationDate"),
                })
        return buckets

    def list_objects(self, bucket: str, prefix: str = "",
                     max_keys: int = 1000) -> list[dict]:
        """GET /<bucket>?list-type=2 — S3 v2 list. Returns
        [{'key','size','etag','last_modified'}].

        Does NOT auto-paginate. Look at .is_truncated on the raw
        response (not exposed here) to detect more pages — future work
        if needed. Cap `max_keys` accordingly for now.
        """
        query = {"list-type": "2", "max-keys": str(max_keys)}
        if prefix:
            query["prefix"] = prefix
        st, _, body = self._request("GET", f"/{bucket}", query, b"")
        if st != 200:
            raise _parse_error(st, body)

        objs = []
        for block in _xml_iter(body, "Contents"):
            key = _xml_field(block, "Key")
            if not key:
                continue
            size_str = _xml_field(block, "Size")
            objs.append({
                "key": key,
                "size": int(size_str) if size_str.isdigit() else 0,
                "etag": _xml_field(block, "ETag").strip('"'),
                "last_modified": _xml_field(block, "LastModified"),
            })
        return objs

    def get_object(self, bucket: str, key: str) -> bytes:
        """GET /<bucket>/<key> — returns body bytes."""
        st, _, body = self._request("GET", f"/{bucket}/{key}", None, b"")
        if st != 200:
            raise _parse_error(st, body)
        return body

    def put_object(self, bucket: str, key: str, data: bytes,
                   content_type: str = "application/octet-stream") -> dict:
        """PUT /<bucket>/<key> — returns response headers dict
        (includes etag)."""
        st, hdrs, body = self._request("PUT", f"/{bucket}/{key}", None,
                                        data, content_type=content_type)
        if st not in (200, 204):
            raise _parse_error(st, body)
        return hdrs

    def stat_object(self, bucket: str, key: str) -> dict:
        """HEAD /<bucket>/<key> — returns
        {'size', 'etag', 'content_type', 'last_modified'}."""
        # amiga.https doesn't reject HEAD, but openssl s_client will
        # get an empty body. That's fine — we only want headers.
        st, hdrs, _ = self._request("HEAD", f"/{bucket}/{key}", None, b"")
        if st != 200:
            raise S3Error(st, "NoSuchKey", f"HEAD returned {st}", b"")
        return {
            "size": int(hdrs.get("content-length", "0")),
            "etag": hdrs.get("etag", "").strip('"'),
            "content_type": hdrs.get("content-type", ""),
            "last_modified": hdrs.get("last-modified", ""),
        }

    def delete_object(self, bucket: str, key: str) -> None:
        """DELETE /<bucket>/<key>. Idempotent — 204 whether or not
        the key existed."""
        st, _, body = self._request("DELETE", f"/{bucket}/{key}", None, b"")
        if st not in (200, 204):
            raise _parse_error(st, body)


# ----------------------------------------------------------------- convenience

# Public MinIO test endpoint. Well-known creds, wide-open sandbox.
# Docs: https://min.io/docs/minio/linux/developers/python/minio-py.html
# These creds rotate very rarely; if they stop working, look at
#   https://play.min.io  for current values.
PLAY_ENDPOINT = "play.min.io"
PLAY_ACCESS = "Q3AM3UQ867SPQQA43P2F"
PLAY_SECRET = "zuf+tfteSlswRu7BJ86wekitnifILbZam1KYY3TG"


def play_client(insecure_tls: bool = False) -> S3Client:
    """Ready-to-use client against play.min.io. For testing only —
    anyone can read anything you upload."""
    return S3Client(PLAY_ENDPOINT, PLAY_ACCESS, PLAY_SECRET,
                    insecure_tls=insecure_tls)
