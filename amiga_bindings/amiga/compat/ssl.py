"""ssl — pure-Python replacement for the stdlib `ssl` module on the
clib4 build of python-os4, where no compiled `_ssl` builtin exists.

Deployment: copy this file to `DH1:lib/ssl.py`. Python's import
machinery finds it (because `DH1:lib` is earlier on `sys.path` than
the stdlib zip) and never reaches the stdlib ssl module.

All symbols and behavior are provided by `amiga.compat.ssl_shim` —
this file just re-exports them so `import ssl` works.

If `amiga.compat.ssl_shim` isn't on `sys.path`, this file falls back
to raising ImportError with a clear message pointing to the missing
module. That would only happen if the amiga_bindings package wasn't
deployed.
"""
try:
    from amiga.compat.ssl_shim import *  # noqa: F401,F403
    from amiga.compat.ssl_shim import (
        SSLContext, SSLError, SSLCertVerificationError,
        CertificateError, TLSVersion, Purpose,
        create_default_context, _create_default_https_context,
        _create_unverified_context, get_default_verify_paths,
        wrap_socket, get_server_certificate,
        PEM_cert_to_DER_cert, DER_cert_to_PEM_cert,
        cert_time_to_seconds, install as _install_shim,
    )
except ImportError as _e:
    raise ImportError(
        f"amiga.compat.ssl_shim not available ({_e}) — the ssl module "
        "on this build depends on it. Deploy the amiga_bindings "
        "package to DH1:lib/amiga/ or use amiga.https.fetch() directly."
    ) from _e
