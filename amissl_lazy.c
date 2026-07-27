/*
 * amissl_lazy.c — replacement for libamisslauto that defers amissl
 * loading until Python's `_ssl` or `_hashlib` module is first imported.
 *
 * Why: libamisslauto uses an ELF constructor that opens amissl.library
 * unconditionally at process startup. Since our `_ssl` and `_hashlib`
 * live as static builtins inside `python-os4`, that ctor fires on
 * every Python invocation — including `python -V`. Consequence:
 * python-os4 refuses to launch on any system without AmiSSL installed,
 * even when the caller never touches SSL.
 *
 * This file replaces libamisslauto's role. It provides the same
 * globals (IAmiSSL, AmiSSLBase, AmiSSLExtBase) — used by the AmiSSL
 * inline macros — but they stay NULL until `_amissl_ensure_open()` is
 * called. Our patched PyInit__ssl / PyInit__hashlib call it as their
 * first act. If it fails, the module raises ImportError and Python
 * carries on running everything else.
 *
 * See Modules-_ssl-lazy.patch and Modules-_hashopenssl-lazy.patch for
 * the CPython source changes that pair with this file.
 */

#include <stdio.h>
#include <string.h>
#include <proto/exec.h>
#include <proto/amissl.h>
#include <proto/amisslmaster.h>
#include <amissl/tags.h>
#include <libraries/amisslmaster.h>

/* Globals the AmiSSL inline macros dereference. Must exist with these
 * exact names & types — they're what libamisslauto also exports.
 * proto/amisslmaster.h + proto/amissl.h also declare `AmiSSLMasterBase`
 * and `IAmiSSLMaster` as extern globals, so we can't shadow them
 * with `static` — provide them as file-scope globals matching the
 * proto declarations. */
struct Library            *AmiSSLBase       = NULL;
struct Library            *AmiSSLExtBase    = NULL;
struct AmiSSLIFace        *IAmiSSL          = NULL;
struct Library            *AmiSSLMasterBase = NULL;
struct AmiSSLMasterIFace  *IAmiSSLMaster    = NULL;
static int  _amissl_tried = 0;
static int  _amissl_ok    = 0;
static char _amissl_err[256] = "amissl not yet initialised";

/* Public: idempotently try to open amissl. Returns 0 on success (or
 * if already open); non-zero on failure. When failing, err_msg gets a
 * human-readable explanation the caller can hand to
 * PyErr_SetString(PyExc_ImportError, ...). */
int _amissl_ensure_open(char *err_msg, unsigned long err_len)
{
    if (_amissl_tried) {
        if (_amissl_ok) return 0;
        if (err_msg && err_len) {
            strncpy(err_msg, _amissl_err, err_len - 1);
            err_msg[err_len - 1] = '\0';
        }
        return 1;
    }
    _amissl_tried = 1;

    /* With __USE_INLINE__ defined, OpenLibrary/GetInterface/etc. are
     * macros that expand to `IExec->OpenLibrary(...)`. Call by plain
     * name — writing `IExec->OpenLibrary` would double-dispatch. */
    AmiSSLMasterBase = OpenLibrary("amisslmaster.library",
                                   AMISSLMASTER_MIN_VERSION);
    if (!AmiSSLMasterBase) {
        snprintf(_amissl_err, sizeof(_amissl_err),
                 "AmiSSL not installed: OpenLibrary amisslmaster.library "
                 "v%ld+ failed", (long)AMISSLMASTER_MIN_VERSION);
        goto fail;
    }
    IAmiSSLMaster = (struct AmiSSLMasterIFace *)GetInterface(
        AmiSSLMasterBase, "main", 1, NULL);
    if (!IAmiSSLMaster) {
        snprintf(_amissl_err, sizeof(_amissl_err),
                 "GetInterface amisslmaster failed (v%ld installed but "
                 "missing 'main' interface)",
                 (long)AmiSSLMasterBase->lib_Version);
        goto fail;
    }
    /* OpenAmiSSLTags is the master library's factory for the actual
     * amissl_v<N>.library instance. Ask for IAmiSSL + AmiSSLBase
     * back so the inline macros work. Skip InitAmiSSL — that ties
     * AmiSSL to a specific bsdsocket base, and Python's _socket has
     * its own (task #94 fd interop). For import-time it doesn't
     * matter; users get HTTPS via amiga.https shell-out. */
    if (OpenAmiSSLTags(
            AMISSL_CURRENT_VERSION,
            AmiSSL_UsesOpenSSLStructs, TRUE,
            AmiSSL_GetIAmiSSL, &IAmiSSL,
            AmiSSL_GetAmiSSLBase, &AmiSSLBase,
            AmiSSL_GetAmiSSLExtBase, &AmiSSLExtBase,
            TAG_DONE) != 0) {
        snprintf(_amissl_err, sizeof(_amissl_err),
                 "OpenAmiSSL failed - amissl_v3xx.library missing in "
                 "LIBS:AmiSSL/? (installer: install-amissl-on-os4.sh)");
        goto fail;
    }
    _amissl_ok = 1;
    if (err_msg && err_len) err_msg[0] = '\0';
    return 0;

fail:
    if (IAmiSSLMaster) {
        DropInterface((struct Interface *)IAmiSSLMaster);
        IAmiSSLMaster = NULL;
    }
    if (AmiSSLMasterBase) {
        CloseLibrary(AmiSSLMasterBase);
        AmiSSLMasterBase = NULL;
    }
    if (err_msg && err_len) {
        strncpy(err_msg, _amissl_err, err_len - 1);
        err_msg[err_len - 1] = '\0';
    }
    return 1;
}
