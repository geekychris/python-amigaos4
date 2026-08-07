/*
 * amiga_shim.h — force-included prototypes for the POSIX shims that
 * CPython source references but newlib doesn't expose in its default
 * feature-set on OS4.
 *
 * Wired via `-include /work/amiga_shim.h` in CFLAGS so every .c
 * file sees these declarations without patching CPython source.
 */
#ifndef AMIGA_SHIM_H
#define AMIGA_SHIM_H

#ifdef __cplusplus
extern "C" {
#endif

/* Shims are gated per libc. Newlib on OS4 is minimal — needs
 * unsetenv, initgroups, setrlimit/getrlimit. Clib2 and clib4 both
 * provide all of these already, so only stub what the target libc
 * lacks. Use the AMIGA_SHIM_NEEDS_POSIX_STUBS macro so a maintainer
 * can override for a new libc without editing three call sites. */
#include <unistd.h>          /* clib2, clib4, newlib all have this */

#if !defined(__CLIB2__) && !defined(__CLIB4__)
#define AMIGA_SHIM_NEEDS_POSIX_STUBS 1
#endif

#ifdef AMIGA_SHIM_NEEDS_POSIX_STUBS
int unsetenv(const char *name);
/* Signature matches clib2's (gid_t = unsigned int) so
 * newlib builds match too when we're the only definer. */
int initgroups(const char *user, unsigned int group);
#endif

#ifdef AMIGA_SHIM_NEEDS_POSIX_STUBS
/* Resource limits — POSIX rlim + setrlimit/getrlimit. Newlib on OS4
 * doesn't ship these. Stubbed to fail with ENOSYS so callers gracefully
 * degrade. faulthandler.c only uses this on Unix crash paths.
 * clib4 provides these natively (see clib4/include/sys/resource.h). */
struct rlimit { unsigned long rlim_cur; unsigned long rlim_max; };
#define RLIMIT_CPU     0
#define RLIMIT_FSIZE   1
#define RLIMIT_DATA    2
#define RLIMIT_STACK   3
#define RLIMIT_CORE    4
#define RLIMIT_RSS     5
#define RLIMIT_NPROC   6
#define RLIMIT_NOFILE  7
#define RLIMIT_AS      9
int setrlimit(int resource, const struct rlimit *rlim);
int getrlimit(int resource, struct rlimit *rlim);
#endif

/* fileno lives in newlib but its prototype isn't visible without a
 * POSIX feature test macro. Declare it here so CPython sees it. */
#include <stdio.h>
int   fileno(FILE *stream);
FILE *fdopen(int fd, const char *mode);
FILE *popen (const char *cmd, const char *mode);
int   pclose(FILE *stream);

/* POSIX open() flags newlib doesn't ship. Stub as 0 = ignored. */
#include <fcntl.h>
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC  0
#endif
#ifndef O_DIRECTORY
#define O_DIRECTORY 0
#endif

/* getrandom(2) — Linux/glibc syscall Python's bootstrap_hash uses.
 * Neither newlib nor OS4 ship an equivalent, and there's no /dev/urandom.
 * Our shim in amiga_shim.c fills the buffer with weak time-based entropy
 * — good enough for dict-hash-seed; NOT cryptographic. */
#include <sys/types.h>
#ifndef GRND_NONBLOCK
#define GRND_NONBLOCK 1
#endif
#ifndef GRND_RANDOM
#define GRND_RANDOM   2
#endif
ssize_t getrandom(void *buf, size_t buflen, unsigned int flags);

/* -------------------------------------------------------------------------
 * nanosleep — autoconf didn't find it on OS4 newlib, but our shim in
 * amiga_shim.c provides one via AmigaDOS Delay().  Force-define
 * HAVE_NANOSLEEP so CPython's pysleep() picks the nanosleep branch
 * instead of the broken select(0,NULL,NULL,NULL,&tv) fallback.
 * ---------------------------------------------------------------------- */
#ifndef HAVE_NANOSLEEP
#define HAVE_NANOSLEEP 1
#endif
/* Newlib on OS4 declares struct timespec but not nanosleep().  Pull
 * in <time.h> for the struct, then forward-declare nanosleep so
 * timemodule.c's implicit-function-declaration error goes away. */
#include <time.h>
int nanosleep(const struct timespec *req, struct timespec *rem);

/* -------------------------------------------------------------------------
 * Network / socket shims — bsdsocket.library exports the BSD socket API
 * through -lsocket, but a handful of POSIX-mandated constants and helpers
 * aren't in newlib's netdb.h.
 * ---------------------------------------------------------------------- */
#ifndef INET_ADDRSTRLEN
#define INET_ADDRSTRLEN  16
#endif
#ifndef INET6_ADDRSTRLEN
#define INET6_ADDRSTRLEN 46
#endif

/* -------------------------------------------------------------------------
 * pthread_mutex_destroy shim — OS4 newlib libpthread returns EBUSY (16)
 * when destroying locks previously associated with condition variables or
 * threads. Shim it to return 0 when status is EBUSY so CPython's
 * CHECK_STATUS_PTHREAD doesn't spam stderr with "Device or resource busy".
 * clib4 uses a different pthread implementation that returns 0 correctly,
 * so the shim is only wired in for newlib builds.
 * ---------------------------------------------------------------------- */
#include <pthread.h>
#ifndef __CLIB4__
int amiga_pthread_mutex_destroy(pthread_mutex_t *mutex);
#define pthread_mutex_destroy amiga_pthread_mutex_destroy
#endif

/* -------------------------------------------------------------------------
 * AmigaOS path normalization shims — OS4 newlib POSIX path translation
 * requires absolute paths to start with '/'. If an Amiga path with a volume
 * colon (e.g. "python3:lib", "System:System/python3") is passed to file
 * functions without a leading '/', newlib treats it as relative to CWD,
 * prepending CWD and corrupting the volume string into "/ython3:" or
 * "/ystem:".
 *
 * clib4 handles Amiga paths natively when enableUnixPaths() is set (or the
 * binary is compiled with `.unix` marker file present). The whole
 * translation stack is disabled for clib4 builds — let its libc do the
 * right thing. If a future clib4 build shows the same path corruption,
 * flip the guard to also enable for __CLIB4__ and add clib4's runtime-
 * detected native-volume list to _newlib_native_volumes[] in amiga_shim.c.
 * ---------------------------------------------------------------------- */
#include <sys/stat.h>
#include <fcntl.h>
#include <dirent.h>
#include <stdarg.h>
#include <utime.h>

#ifndef __CLIB4__
const char *amiga_to_posix_path(const char *path, char *buf, size_t buflen);
int amiga_stat(const char *path, struct stat *buf);
int amiga_lstat(const char *path, struct stat *buf);
int amiga_access(const char *path, int mode);
int amiga_open(const char *path, int flags, ...);
DIR *amiga_opendir(const char *name);
FILE *amiga_fopen(const char *filename, const char *mode);
FILE *amiga_freopen(const char *filename, const char *mode, FILE *stream);
int amiga_chdir(const char *path);
int amiga_mkdir(const char *path, mode_t mode);
int amiga_rmdir(const char *path);
int amiga_unlink(const char *path);
int amiga_remove(const char *path);
int amiga_rename(const char *oldpath, const char *newpath);
char *amiga_realpath(const char *path, char *resolved_path);
ssize_t amiga_readlink(const char *path, char *buf, size_t bufsiz);
int amiga_chmod(const char *path, mode_t mode);
int amiga_utime(const char *filename, const struct utimbuf *times);

#define stat(p, b) amiga_stat(p, b)
#define lstat(p, b) amiga_lstat(p, b)
#define access(p, m) amiga_access(p, m)
#define open(p, ...) amiga_open(p, __VA_ARGS__)
#define opendir(n) amiga_opendir(n)
#define fopen(f, m) amiga_fopen(f, m)
#define freopen(f, m, s) amiga_freopen(f, m, s)
#define chdir(p) amiga_chdir(p)
#define mkdir(p, m) amiga_mkdir(p, m)
#define rmdir(p) amiga_rmdir(p)
#define unlink(p) amiga_unlink(p)
#define remove(p) amiga_remove(p)
#define rename(o, n) amiga_rename(o, n)
#define realpath(p, r) amiga_realpath(p, r)
#define readlink(p, b, s) amiga_readlink(p, b, s)
#define chmod(p, m) amiga_chmod(p, m)
#define utime(f, t) amiga_utime(f, t)
#endif /* !__CLIB4__ */

#ifdef __cplusplus
}
#endif

#endif
