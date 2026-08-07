/*
 * amiga_shim_fixed.c — POSIX shims for CPython on AmigaOS 4.
 *
 * This version intentionally contains NO __gthread_* definitions.
 * GCC supplies the native AmigaOS gthread backend when the final link
 * uses -athread=native.
 */
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <stdint.h>
#include "amiga_shim.h"

#ifdef AMIGA_SHIM_NEEDS_POSIX_STUBS
int unsetenv(const char *name)
{
    if (!name || !*name) return -1;
    return setenv(name, "", 1);
}

int initgroups(const char *user, unsigned int group)
{
    (void)user;
    (void)group;
    return 0;
}

int setrlimit(int resource, const struct rlimit *rlim)
{
    (void)resource;
    (void)rlim;
    errno = ENOSYS;
    return -1;
}

int getrlimit(int resource, struct rlimit *rlim)
{
    (void)resource;
    if (rlim) {
        rlim->rlim_cur = 0;
        rlim->rlim_max = 0;
    }
    errno = ENOSYS;
    return -1;
}
#endif

/* OS4 newlib routes ioctl through bsdsocket. These operations have no
 * meaningful effect on AmigaDOS file handles, so accept them. */
int ioctl(int fd, unsigned long request, ...)
{
    (void)fd;
    (void)request;
    return 0;
}

#include <stdarg.h>
int fcntl(int fd, int cmd, ...)
{
    (void)fd;
    switch (cmd) {
    case 1: /* F_GETFD */
    case 3: /* F_GETFL */
        return 0;
    case 2: /* F_SETFD */
    case 4: /* F_SETFL */
        return 0;
    default:
        errno = ENOSYS;
        return -1;
    }
}

#include <time.h>
#include <unistd.h>
ssize_t getrandom(void *buf, size_t buflen, unsigned int flags)
{
    (void)flags;
    if (!buf) {
        errno = EFAULT;
        return -1;
    }

    unsigned long seed = (unsigned long)time(NULL);
    seed ^= (unsigned long)(uintptr_t)buf;
    seed ^= (unsigned long)(uintptr_t)&seed << 3;

    unsigned char *out = (unsigned char *)buf;
    for (size_t i = 0; i < buflen; ++i) {
        seed = seed * 1664525UL + 1013904223UL;
        out[i] = (unsigned char)((seed >> 16) & 0xff);
    }
    return (ssize_t)buflen;
}

#include <proto/dos.h>
#include <time.h>
int nanosleep(const struct timespec *req, struct timespec *rem)
{
    if (rem) {
        rem->tv_sec = 0;
        rem->tv_nsec = 0;
    }
    if (!req) {
        errno = EINVAL;
        return -1;
    }
    if (req->tv_sec < 0 || req->tv_nsec < 0 || req->tv_nsec >= 1000000000L) {
        errno = EINVAL;
        return -1;
    }

    unsigned long ticks = (unsigned long)req->tv_sec * 50UL;
    unsigned long extra = (unsigned long)req->tv_nsec / 20000000UL;
    if (req->tv_nsec % 20000000L != 0) ++extra;
    ticks += extra;
    if (ticks == 0) ticks = 1;

    Delay(ticks);
    return 0;
}

#ifndef __CLIB4__
#undef pthread_mutex_destroy
int amiga_pthread_mutex_destroy(pthread_mutex_t *mutex)
{
    if (mutex) memset(mutex, 0, sizeof(pthread_mutex_t));
    return 0;
}
#endif

#include <proto/exec.h>
#include <dos/dos.h>
__attribute__((constructor)) static void amiga_suppress_requesters(void)
{
    if (IExec) {
        struct Process *proc = (struct Process *)FindTask(NULL);
        if (proc && proc->pr_Task.tc_Node.ln_Type == NT_PROCESS) {
            proc->pr_WindowPtr = (APTR)-1;
        }
    }
}

/* -------------------------------------------------------------------------
 * All code below this point is newlib-specific — path translation and
 * the amiga_* wrappers that macro-substitute stdlib file operations.
 * clib4 provides Amiga-path handling natively (enableUnixPaths()), so
 * we compile none of this for clib4 builds. If a clib4 build shows
 * similar path corruption, remove the guard, and add clib4-native
 * volumes to _newlib_native_volumes[] below.
 * ---------------------------------------------------------------------- */
#ifndef __CLIB4__

/* Volume-name prefixes newlib recognises natively on OS4. For these,
 * VOL:path form works AND writes land in the real AmigaDOS-visible
 * filesystem. For anything NOT in this list (custom assigns like
 * System:, python3:, LIBS:, ...), newlib prepends CWD and corrupts
 * to /ystem: / /ython3: (Bill's bug from commit 130d850), so we
 * MUST translate to /VOL/path form for those.
 *
 * Case-insensitive prefix match. Order irrelevant; longest-match
 * not needed because volumes end at ':'.
 *
 * Additions here should be verified with the on-guest smoke test
 * (tests/on_guest/smoke.py — write_file_via_open + read_own_write). */
static const char *const _newlib_native_volumes[] = {
    "T:",       "RAM:",    "SYS:",     "PROGDIR:",
    "CON:",     "NIL:",    "RAW:",     "PIPE:",
    "DH0:",     "DH1:",    "DH2:",     "DH3:",
    "DH4:",     "DH5:",    "DH6:",     "DH7:",
    "DH8:",     "DH9:",    "DF0:",     "DF1:",
    "CD0:",     "CD1:",
    NULL
};

static int _is_newlib_native_volume(const char *path)
{
    if (!path) return 0;
    for (const char *const *v = _newlib_native_volumes; *v; v++) {
        size_t len = 0;
        while ((*v)[len]) len++;
        if (strncasecmp(path, *v, len) == 0) return 1;
    }
    return 0;
}

const char *amiga_to_posix_path(const char *path, char *buf, size_t buflen)
{
    /* Only translate VOL:path → /VOL/path when the volume is NOT
     * one newlib knows natively. Native volumes must pass through
     * untouched — otherwise newlib creates a virtual file at
     * /VOL/path that AmigaDOS `list` never sees (silent-write bug).
     *
     * Non-native volumes MUST translate — otherwise newlib prepends
     * CWD and corrupts the path to /ystem: / /ython3: (Bill's
     * commit 130d850 bug — triggers "Please insert volume /ystem:"
     * requester). */
    if (!path || !*path || !buf || buflen < 4) return path;
    if (path[0] == '/') return path;

    const char *colon = strchr(path, ':');
    const char *slash = strchr(path, '/');
    const char *backslash = strchr(path, '\\');

    if (colon && colon > path && (!slash || colon < slash) &&
        (!backslash || colon < backslash)) {
        if (_is_newlib_native_volume(path)) return path;  /* pass through */
        size_t vol_len = (size_t)(colon - path);
        const char *rest = colon + 1;
        if (rest[0] == '/' || rest[0] == '\\') ++rest;
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

/* -------------------------------------------------------------------------
 * Since amiga_to_posix_path is now allowlist-aware (native volumes
 * pass through unchanged; only custom assigns get /VOL/path form),
 * we simply pass the translated result to the underlying libc call.
 * The old "try both and fall back" dance was needed when we
 * over-translated; the allowlist eliminates that need.
 *
 * The raw `stat`/`open`/`fopen`/etc. calls in this file resolve to
 * the libc originals (macros are #undef'd above), no recursion.
 * ---------------------------------------------------------------------- */

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
    const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
    }
    return open(tp, flags, mode);
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
    return freopen(amiga_to_posix_path(filename, pbuf, sizeof(pbuf)),
                    mode, stream);
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
    char oldbuf[1024], newbuf[1024];
    const char *to = amiga_to_posix_path(oldpath, oldbuf, sizeof(oldbuf));
    const char *tn = amiga_to_posix_path(newpath, newbuf, sizeof(newbuf));
    int r = rename(to, tn);
    if (r != 0 && (to != oldpath || tn != newpath)) {
        errno = 0; r = rename(oldpath, newpath);
    }
    return r;
}

char *amiga_realpath(const char *path, char *resolved_path)
{
    char pbuf[1024];
    const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
    char *r = realpath(tp, resolved_path);
    if (!r && tp != path) { errno = 0; r = realpath(path, resolved_path); }
    return r;
}

ssize_t amiga_readlink(const char *path, char *buf, size_t bufsiz)
{
    char pbuf[1024];
    const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
    ssize_t r = readlink(tp, buf, bufsiz);
    if (r < 0 && tp != path) { errno = 0; r = readlink(path, buf, bufsiz); }
    return r;
}

int amiga_chmod(const char *path, mode_t mode)
{
    char pbuf[1024];
    const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
    int r = chmod(tp, mode);
    if (r != 0 && tp != path) { errno = 0; r = chmod(path, mode); }
    return r;
}

int amiga_utime(const char *filename, const struct utimbuf *times)
{
    char pbuf[1024];
    const char *tp = amiga_to_posix_path(filename, pbuf, sizeof(pbuf));
    int r = utime(tp, times);
    if (r != 0 && tp != filename) { errno = 0; r = utime(filename, times); }
    return r;
}

#endif /* !__CLIB4__ — path-translation wrappers */
