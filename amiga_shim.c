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

#ifndef __CLIB2__
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

#undef pthread_mutex_destroy
int amiga_pthread_mutex_destroy(pthread_mutex_t *mutex)
{
    if (mutex) memset(mutex, 0, sizeof(pthread_mutex_t));
    return 0;
}

#include <proto/exec.h>
#include <proto/dos.h>
#include <dos/dos.h>
__attribute__((constructor)) static void amiga_suppress_requesters(void)
{
    if (IExec) {
        struct Process *proc = (struct Process *)FindTask(NULL);
        if (proc && proc->pr_Task.tc_Node.ln_Type == NT_PROCESS) {
            proc->pr_WindowPtr = (APTR)-1;
        }
    }
    if (IDOS) {
        SetProcWindow((APTR)-1);
    }
}

const char *amiga_to_posix_path(const char *path, char *buf, size_t buflen)
{
    if (!path || !*path || !buf || buflen < 4) return path;

    /* Handle /VOL:rest or /VOL:/rest forms */
    if (path[0] == '/') {
        const char *colon = strchr(path, ':');
        if (colon) {
            size_t prefix_len = (size_t)(colon - path);
            const char *rest = colon + 1;
            if (rest[0] == '/' || rest[0] == '\\') ++rest;
            snprintf(buf, buflen, "%.*s/%s", (int)prefix_len, path, rest);
            return buf;
        }
        return path;
    }

    const char *colon = strchr(path, ':');
    const char *slash = strchr(path, '/');
    const char *backslash = strchr(path, '\\');

    if (colon && colon > path && (!slash || colon < slash) &&
        (!backslash || colon < backslash)) {
        size_t vol_len = (size_t)(colon - path);
        const char *rest = colon + 1;
        if (rest[0] == '/' || rest[0] == '\\') ++rest;
        snprintf(buf, buflen, "/%.*s/%s", (int)vol_len, path, rest);
        return buf;
    }

    /* If relative path starts with a known volume/assign name e.g. "System/...", "python3/..." */
    if (slash && slash > path) {
        size_t seg_len = (size_t)(slash - path);
        if (seg_len == 6 && strncasecmp(path, "System", 6) == 0) {
            snprintf(buf, buflen, "/%s", path);
            return buf;
        }
        if (seg_len == 7 && strncasecmp(path, "python3", 7) == 0) {
            snprintf(buf, buflen, "/%s", path);
            return buf;
        }
        if (seg_len == 3 && (strncasecmp(path, "SYS", 3) == 0 || strncasecmp(path, "RAM", 3) == 0)) {
            snprintf(buf, buflen, "/%s", path);
            return buf;
        }
        if (seg_len == 4 && strncasecmp(path, "Work", 4) == 0) {
            snprintf(buf, buflen, "/%s", path);
            return buf;
        }
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
 * Try-original-first strategy: pass the AmigaDOS-native VOL:path
 * form to newlib FIRST, and only fall back to Bill's /VOL/path
 * translation if that fails.
 *
 * Rationale: for the assigns newlib knows about natively (T:, RAM:,
 * SYS:, DH0-9), VOL:path just works and writes land in the
 * AmigaDOS-visible location. For custom assigns like `python3:`,
 * VOL:path fails (Bill's commit 130d850 corruption case) and we
 * fall through to /VOL/path.
 *
 * The earlier /VOL/path-first order broke user-code file writes:
 * newlib accepted /T/foo, returned a valid fd, but writes landed
 * in a virtual location AmigaDOS never saw. Trying VOL:path first
 * puts the file where the OS looks for it.
 * ---------------------------------------------------------------------- */

int amiga_stat(const char *path, struct stat *buf)
{
    int r = stat(path, buf);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = stat(tp, buf); }
    }
    return r;
}

int amiga_lstat(const char *path, struct stat *buf)
{
    int r = lstat(path, buf);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = lstat(tp, buf); }
    }
    return r;
}

int amiga_access(const char *path, int mode)
{
    int r = access(path, mode);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = access(tp, mode); }
    }
    return r;
}

int amiga_open(const char *path, int flags, ...)
{
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, mode_t);
        va_end(ap);
    }
    int fd = open(path, flags, mode);
    if (fd < 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; fd = open(tp, flags, mode); }
    }
    return fd;
}

DIR *amiga_opendir(const char *name)
{
    DIR *d = opendir(name);
    if (!d) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(name, pbuf, sizeof(pbuf));
        if (tp != name) { errno = 0; d = opendir(tp); }
    }
    return d;
}

FILE *amiga_fopen(const char *filename, const char *mode)
{
    FILE *f = fopen(filename, mode);
    if (!f) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(filename, pbuf, sizeof(pbuf));
        if (tp != filename) { errno = 0; f = fopen(tp, mode); }
    }
    return f;
}

FILE *amiga_freopen(const char *filename, const char *mode, FILE *stream)
{
    FILE *f = freopen(filename, mode, stream);
    if (!f) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(filename, pbuf, sizeof(pbuf));
        if (tp != filename) { errno = 0; f = freopen(tp, mode, stream); }
    }
    return f;
}

int amiga_chdir(const char *path)
{
    int r = chdir(path);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = chdir(tp); }
    }
    return r;
}

int amiga_mkdir(const char *path, mode_t mode)
{
    int r = mkdir(path, mode);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = mkdir(tp, mode); }
    }
    return r;
}

int amiga_rmdir(const char *path)
{
    int r = rmdir(path);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = rmdir(tp); }
    }
    return r;
}

int amiga_unlink(const char *path)
{
    int r = unlink(path);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = unlink(tp); }
    }
    return r;
}

int amiga_remove(const char *path)
{
    int r = remove(path);
    if (r != 0) {
        char pbuf[1024];
        const char *tp = amiga_to_posix_path(path, pbuf, sizeof(pbuf));
        if (tp != path) { errno = 0; r = remove(tp); }
    }
    return r;
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
