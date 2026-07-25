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
 * unsetenv, initgroups, setrlimit/getrlimit. Clib2 provides all
 * of these already, so only stub what the target libc lacks. */
#include <unistd.h>          /* both clib2 and newlib have this */

#ifndef __CLIB2__
int unsetenv(const char *name);
/* Signature matches clib2's (gid_t = unsigned int) so
 * newlib builds match too when we're the only definer. */
int initgroups(const char *user, unsigned int group);
#endif

#ifndef __CLIB2__
/* Resource limits — POSIX rlim + setrlimit/getrlimit. Newlib on OS4
 * doesn't ship these. Stubbed to fail with ENOSYS so callers gracefully
 * degrade. faulthandler.c only uses this on Unix crash paths. */
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

#ifdef __cplusplus
}
#endif

#endif
