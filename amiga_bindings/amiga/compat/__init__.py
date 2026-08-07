"""amiga.compat — pure-Python replacements for stdlib modules that
either don't build on the target libc (clib4 lacks a working stdlib
`_ssl`) or ship a known-broken implementation (task #94: newlib
`_ssl`/`_socket` fd interop is broken).

Modules:
  ssl_shim — full-surface stdlib `ssl` module replacement that routes
             HTTPS through amiga.https (which shells to the standalone
             openssl binary).

Typical deployment: for the clib4 python-os4 build, `ssl_shim.py` is
also installed as `DH1:lib/ssl.py` so that `import ssl` transparently
gets our stub (no `_ssl` builtin present to win the import race).

See docs/CLIB4_BUILD.md and docs/AMIGA_SSL_SHIM.md for the design
notes.
"""
