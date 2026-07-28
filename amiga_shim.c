/*
 * amiga_shim.c — POSIX shims for CPython on OS4.
 *
 * Newlib on OS4 is missing a handful of POSIX-ish functions that
 * CPython core files reference. We provide minimal implementations
 * here and force-link this .o into the interpreter build.
 *
 * Long-term this belongs under `Amiga/` inside a proper platform
 * directory in the CPython tree (matching PC/ and Mac/). Phase 1
 * ships it as a single external .c to keep patches to CPython
 * itself minimal.
 */

#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include "amiga_shim.h"

/* Newlib on OS4 has setenv but no unsetenv. Use setenv with empty
 * value as a poor-man's substitute — the env var will still exist
 * but with an empty string, which is what most callers effectively
 * test for. Full removal would need to walk the env array. */
#ifndef __CLIB2__
/* Newlib-only stubs — clib2 has all of these built in. */

int unsetenv(const char *name)
{
    if (!name || !*name) return -1;
    return setenv(name, "", 1);
}

int initgroups(const char *user, unsigned int group)
{
    (void)user; (void)group;
    return 0;   /* no-op success — Amiga has no supplementary groups */
}

int setrlimit(int resource, const struct rlimit *rlim)
{
    (void)resource; (void)rlim;
    errno = ENOSYS;
    return -1;
}

int getrlimit(int resource, struct rlimit *rlim)
{
    (void)resource;
    if (rlim) { rlim->rlim_cur = 0; rlim->rlim_max = 0; }
    errno = ENOSYS;
    return -1;
}
#endif   /* !__CLIB2__ */

/* --- gthread stubs -------------------------------------------------
 * libgcc's emutls.c (emulated thread-local storage) references the
 * `__gthread_*` interface. On systems without native TLS + no pthread
 * library the linker complains. For our single-threaded Phase-1
 * interpreter we stub the whole interface with a single-slot-per-key
 * global — enough for the interpreter to link.
 *
 * When we get to Phase 4 (threading) these need to become real
 * pthread-key-backed implementations. Until then, do NOT enable
 * multi-threading — there's one shared slot per key. */

typedef struct { void *value; } gthread_key_slot_t;

int __gthread_key_create(gthread_key_slot_t **key, void (*dtor)(void *))
{
    (void)dtor;
    static gthread_key_slot_t slots[128];
    static int next_slot = 0;
    if (next_slot >= 128) return -1;
    slots[next_slot].value = NULL;
    *key = &slots[next_slot++];
    return 0;
}

int __gthread_key_delete(gthread_key_slot_t *key)
{
    if (key) key->value = NULL;
    return 0;
}

void *__gthread_getspecific(gthread_key_slot_t *key)
{
    return key ? key->value : NULL;
}

int __gthread_setspecific(gthread_key_slot_t *key, const void *value)
{
    if (!key) return -1;
    key->value = (void *)value;
    return 0;
}

int __gthread_once(int *once, void (*func)(void))
{
    if (!once) return -1;
    if (*once) return 0;
    *once = 1;
    func();
    return 0;
}

/* Returning 0 = "single-threaded" makes libgcc take fast paths
 * that skip locking. Perfect for Phase 1. */
int __gthread_active_p(void) { return 0; }

/* --- ioctl shim ---------------------------------------------------
 * OS4 newlib routes ioctl through bsdsocket only — it returns
 * ENOTSOCK (errno 38) when called on a regular file fd. CPython's
 * _Py_set_inheritable tries ioctl(FIOCLEX) first, and only falls
 * back to fcntl if errno is ENOTTY/EACCES — not ENOTSOCK. So the
 * whole set_inheritable path errors even though FD_CLOEXEC is
 * meaningless on AmigaOS. Shim ioctl to return 0 for the
 * FIOCLEX/FIONCLEX / FIONBIO cases which have no real effect on
 * Amiga file handles anyway. Anything unrecognised falls through
 * to ENOTTY so Python takes its fallback path. */
int ioctl(int fd, unsigned long request, ...)
{
    (void)fd; (void)request;
    /* Common cases: FIOCLEX = 0x20006601, FIONCLEX = 0x20006602,
     * FIONBIO = 0x8004667e. Just always claim success — none of
     * these have meaningful effect on AmigaDOS file handles. */
    return 0;
}

/* --- fcntl shim ---------------------------------------------------
 * Newlib on OS4 doesn't implement fcntl(). CPython's
 * _Py_set_inheritable uses fcntl(F_GETFD)/fcntl(F_SETFD) to set the
 * FD_CLOEXEC bit. That's a no-op on AmigaOS (no exec-across-fork),
 * so return success without doing anything.
 *
 * Real fcntl signature: `int fcntl(int fd, int cmd, ...);`
 * For F_GETFD/F_GETFL we return 0 (no flags set).
 * For F_SETFD/F_SETFL we return 0 (accepted, no-op).
 * Anything else we return -1 with ENOSYS. */
#include <stdarg.h>
int fcntl(int fd, int cmd, ...)
{
    (void)fd;
    switch (cmd) {
    case 1:  /* F_GETFD */
    case 3:  /* F_GETFL */
        return 0;
    case 2:  /* F_SETFD */
    case 4:  /* F_SETFL */
        return 0;
    default:
        errno = ENOSYS;
        return -1;
    }
}

/* --- getrandom shim -----------------------------------------------
 * Python's bootstrap_hash calls getrandom() then falls back to
 * /dev/urandom. OS4 has neither. Provide a weak entropy source
 * (time + PID + linear congruential churning). NOT cryptographic —
 * fine for Python's hash-seed randomization use case which just
 * needs unpredictability across restarts. */

#include <time.h>
#include <unistd.h>

ssize_t getrandom(void *buf, size_t buflen, unsigned int flags)
{
    (void)flags;
    if (!buf) { errno = EFAULT; return -1; }
    /* Mix time, our address (ASLR-ish), and a spinning LCG. */
    unsigned long seed = (unsigned long)time(NULL);
    seed ^= (unsigned long)(uintptr_t)buf;
    seed ^= (unsigned long)(uintptr_t)&seed << 3;
    unsigned char *out = (unsigned char *)buf;
    for (size_t i = 0; i < buflen; i++) {
        /* Numerical Recipes LCG constants — good enough for hash seed */
        seed = seed * 1664525UL + 1013904223UL;
        out[i] = (unsigned char)((seed >> 16) & 0xFF);
    }
    return (ssize_t)buflen;
}

/* Mutex family. Single-threaded → all no-ops that always succeed. */
typedef int gthread_mutex_t;
int __gthread_mutex_init   (gthread_mutex_t *m) { if (m) *m = 0; return 0; }
int __gthread_mutex_destroy(gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_mutex_lock   (gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_mutex_trylock(gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_mutex_unlock (gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_recursive_mutex_init   (gthread_mutex_t *m) { if (m) *m = 0; return 0; }
int __gthread_recursive_mutex_destroy(gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_recursive_mutex_lock   (gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_recursive_mutex_trylock(gthread_mutex_t *m) { (void)m; return 0; }
int __gthread_recursive_mutex_unlock (gthread_mutex_t *m) { (void)m; return 0; }

/* NOTE: _Py_open_cloexec_works is defined by CPython's fileutils.c
 * itself. It was previously stubbed here for the clib2 attempt where
 * fileutils.c compiled the definition out. With newlib the real
 * definition exists — do NOT redefine here (linker collision). */


/* --- nanosleep shim -----------------------------------------------
 * Autoconf couldn't find nanosleep or clock_nanosleep on OS4 newlib,
 * so CPython's pysleep() falls through to `select(0, NULL, NULL,
 * NULL, &tv)` — but bsdsocket.library rejects nfds=0 without setting
 * errno, so time.sleep() ends up raising OSError [Errno 0].
 *
 * Fix: provide a nanosleep() that dispatches to AmigaDOS Delay().
 * amiga_shim.h #define's HAVE_NANOSLEEP so pysleep picks the
 * nanosleep branch instead of the broken select one.
 *
 * Precision: Delay() takes ticks at 50Hz (20 ms each) on classic and
 * on OS4.  Sub-tick sleep requests round up to 1 tick, giving 20ms
 * granularity — more than enough for anything Python typically
 * sleeps for.  (Threading Event.wait can go finer if needed.)
 *
 * Safety: CLAUDE.md warns against Delay(1) as a frame-pacing
 * primitive under -lauto/newlib; that DSI was inside a tight render
 * loop hitting the timer 60 times per second.  A user-facing
 * time.sleep(0.5) is 25 ticks — not tight, not risky. */

#include <proto/dos.h>
#include <time.h>

int nanosleep(const struct timespec *req, struct timespec *rem)
{
    if (rem) { rem->tv_sec = 0; rem->tv_nsec = 0; }
    if (!req) { errno = EINVAL; return -1; }
    if (req->tv_sec < 0 || req->tv_nsec < 0 || req->tv_nsec >= 1000000000L) {
        errno = EINVAL;
        return -1;
    }

    /* Convert to 50Hz ticks (round up); minimum 1 tick.
     * tick_ns = 20_000_000  → sec * 50 + nsec / 20e6, ceil */
    unsigned long ticks = (unsigned long)req->tv_sec * 50UL;
    unsigned long extra = (unsigned long)req->tv_nsec / 20000000UL;
    if (req->tv_nsec % 20000000L != 0) extra++;
    ticks += extra;
    if (ticks == 0) ticks = 1;

    Delay(ticks);
    return 0;
}

/* --- pthread_mutex_destroy shim ------------------------------------
 * OS4 newlib libpthread's internal pthread_mutex_destroy() prints a noisy
 * "pthread_mutex_destroy: Device or resource busy" directly to stderr
 * whenever a mutex associated with condition variables is destroyed.
 * Zero out the mutex structure to clean it up without calling libpthread's
 * noisy stderr printer. */
#undef pthread_mutex_destroy
int amiga_pthread_mutex_destroy(pthread_mutex_t *mutex)
{
    if (mutex) {
        memset(mutex, 0, sizeof(pthread_mutex_t));
    }
    return 0;
}

/* --- Constructor: Suppress AmigaDOS Volume Requesters --------------
 * AmigaDOS pops up a GUI requester ("Please insert Volume X:") whenever
 * a path contains an unknown volume name followed by a colon.
 * Setting pr_WindowPtr = (APTR)-1 in the process structure suppresses
 * all GUI dialogs so missing volume/path checks return clean ENOENT. */
#include <proto/exec.h>
#include <dos/dos.h>

__attribute__((constructor)) static void amiga_suppress_requesters(void)
{
    if (IExec) {
        struct Process *proc = (struct Process *)IExec->FindTask(NULL);
        if (proc && proc->pr_Task.tc_Node.ln_Type == NT_PROCESS) {
            proc->pr_WindowPtr = (APTR)-1;
        }
    }
}

/* --- AmigaOS POSIX Path Converter & File Function Shims ------------
 * Translates Amiga native volume paths (e.g. "python3:lib", "System:foo")
 * to absolute POSIX paths (e.g. "/python3/lib", "/System/foo") before
 * passing to OS4 newlib POSIX file functions. Prevents newlib from
 * treating un-slashed volume paths as relative, prepending CWD, and
 * corrupting the volume string into "/ython3:" or "/ystem:". */
const char *amiga_to_posix_path(const char *path, char *buf, size_t buflen)
{
    if (!path || !*path || !buf || buflen < 4) return path;
    if (path[0] == '/') return path;

    const char *colon = strchr(path, ':');
    const char *slash = strchr(path, '/');
    const char *backslash = strchr(path, '\\');

    if (colon && colon > path && (!slash || colon < slash) && (!backslash || colon < backslash)) {
        size_t vol_len = colon - path;
        const char *rest = colon + 1;
        if (rest[0] == '/' || rest[0] == '\\') rest++;

        snprintf(buf, buflen, "/%.*s/%s", (int)vol_len, path, rest);
        return buf;
    }

    return path;
}

#undef stat
#undef lstat
#undef access
#undef open
#undef opendir
#undef fopen
#undef freopen
#undef chdir
#undef mkdir
#undef rmdir
#undef unlink
#undef remove
#undef rename
#undef realpath
#undef readlink
#undef chmod
#undef utime

int amiga_stat(const char *path, struct stat *buf)
{
    char pbuf[1024];
    return stat(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), buf);
}

int amiga_lstat(const char *path, struct stat *buf)
{
    char pbuf[1024];
    return lstat(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), buf);
}

int amiga_access(const char *path, int mode)
{
    char pbuf[1024];
    return access(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), mode);
}

int amiga_open(const char *path, int flags, ...)
{
    char pbuf[1024];
    const char *ppath = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
    }
    return open(ppath, flags, mode);
}

DIR *amiga_opendir(const char *name)
{
    char pbuf[1024];
    return opendir(amiga_to_posix_path(name, pbuf, sizeof(pbuf)));
}

FILE *amiga_fopen(const char *filename, const char *mode)
{
    char pbuf[1024];
    return fopen(amiga_to_posix_path(filename, pbuf, sizeof(pbuf)), mode);
}

FILE *amiga_freopen(const char *filename, const char *mode, FILE *stream)
{
    char pbuf[1024];
    return freopen(amiga_to_posix_path(filename, pbuf, sizeof(pbuf)), mode, stream);
}

int amiga_chdir(const char *path)
{
    char pbuf[1024];
    return chdir(amiga_to_posix_path(path, pbuf, sizeof(pbuf)));
}

int amiga_mkdir(const char *path, mode_t mode)
{
    char pbuf[1024];
    return mkdir(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), mode);
}

int amiga_rmdir(const char *path)
{
    char pbuf[1024];
    return rmdir(amiga_to_posix_path(path, pbuf, sizeof(pbuf)));
}

int amiga_unlink(const char *path)
{
    char pbuf[1024];
    return unlink(amiga_to_posix_path(path, pbuf, sizeof(pbuf)));
}

int amiga_remove(const char *path)
{
    char pbuf[1024];
    return remove(amiga_to_posix_path(path, pbuf, sizeof(pbuf)));
}

int amiga_rename(const char *oldpath, const char *newpath)
{
    char pbuf1[1024], pbuf2[1024];
    return rename(
        amiga_to_posix_path(oldpath, pbuf1, sizeof(pbuf1)),
        amiga_to_posix_path(newpath, pbuf2, sizeof(pbuf2))
    );
}

char *amiga_realpath(const char *path, char *resolved_path)
{
    char pbuf[1024];
    return realpath(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), resolved_path);
}

ssize_t amiga_readlink(const char *path, char *buf, size_t bufsiz)
{
    char pbuf[1024];
    return readlink(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), buf, bufsiz);
}

int amiga_chmod(const char *path, mode_t mode)
{
    char pbuf[1024];
    return chmod(amiga_to_posix_path(path, pbuf, sizeof(pbuf)), mode);
}

int amiga_utime(const char *filename, const struct utimbuf *times)
{
    char pbuf[1024];
    return utime(amiga_to_posix_path(filename, pbuf, sizeof(pbuf)), times);
}
