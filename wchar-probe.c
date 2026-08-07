/* Minimal clib4 vs newlib wchar/path probe. Exercises the same
 * operations CPython does during pymain_init:
 *   - mbstowcs on Amiga volume path
 *   - realpath on Amiga volume path
 *   - wcsdup
 *   - PyOS_getenv equivalent
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <wchar.h>
#include <errno.h>
extern char *realpath(const char *path, char *resolved_path);

static void log_result(const char *label, int ok, const char *detail) {
    printf("  %-30s %s %s\n", label, ok ? "OK" : "FAIL", detail ? detail : "");
    fflush(stdout);
}

int main(int argc, char **argv) {
    printf("=== wchar/path probe ===\n");
    printf("argc=%d, argv[0]=%s\n", argc, argv[0]);
    fflush(stdout);

    /* Test 1: mbstowcs on ASCII */
    {
        wchar_t buf[256];
        size_t n = mbstowcs(buf, "hello", 256);
        char msg[64];
        snprintf(msg, sizeof(msg), "n=%zu", n);
        log_result("mbstowcs('hello')", n == 5, msg);
    }

    /* Test 2: mbstowcs on Amiga volume path */
    {
        wchar_t buf[256];
        size_t n = mbstowcs(buf, "DH1:python-os4-clib4/python-os4", 256);
        char msg[128];
        if (n == (size_t)-1) {
            snprintf(msg, sizeof(msg), "n=-1 errno=%d(%s)", errno, strerror(errno));
        } else {
            snprintf(msg, sizeof(msg), "n=%zu", n);
        }
        log_result("mbstowcs('DH1:...')", n != (size_t)-1, msg);
    }

    /* Test 3: mbstowcs NULL query (returns needed length) */
    {
        size_t n = mbstowcs(NULL, "DH1:python-os4-clib4/python-os4", 0);
        char msg[64];
        snprintf(msg, sizeof(msg), "n=%zd", (ssize_t)n);
        log_result("mbstowcs(NULL,...)", n != (size_t)-1, msg);
    }

    /* Test 4: realpath on Amiga volume path */
    {
        char resolved[1024];
        char *r = realpath("DH1:python-os4-clib4/python-os4", resolved);
        char msg[512];
        if (r == NULL) {
            snprintf(msg, sizeof(msg), "NULL errno=%d(%s)", errno, strerror(errno));
        } else {
            snprintf(msg, sizeof(msg), "→ %s", resolved);
        }
        log_result("realpath('DH1:...')", r != NULL, msg);
    }

    /* Test 5: realpath on argv[0] */
    {
        char resolved[1024];
        char *r = realpath(argv[0], resolved);
        char msg[512];
        if (r == NULL) {
            snprintf(msg, sizeof(msg), "NULL errno=%d(%s)", errno, strerror(errno));
        } else {
            snprintf(msg, sizeof(msg), "→ %s", resolved);
        }
        log_result("realpath(argv[0])", r != NULL, msg);
    }

    /* Test 6: getenv PYTHONHOME */
    {
        const char *v = getenv("PYTHONHOME");
        char msg[512];
        snprintf(msg, sizeof(msg), "= %s", v ? v : "(unset)");
        log_result("getenv(PYTHONHOME)", 1, msg);
    }

    /* Test 7: wcsdup */
    {
        wchar_t src[64];
        mbstowcs(src, "DH1:python-os4-clib4", 64);
        wchar_t *dup = wcsdup(src);
        char msg[64];
        snprintf(msg, sizeof(msg), "dup=%p", (void*)dup);
        log_result("wcsdup", dup != NULL, msg);
        if (dup) free(dup);
    }

    /* Test 8: malloc reasonable size */
    {
        void *p = malloc(4096);
        char msg[64];
        snprintf(msg, sizeof(msg), "p=%p", p);
        log_result("malloc(4096)", p != NULL, msg);
        if (p) free(p);
    }

    /* Test 9: setlocale — CPython calls this */
    #include <locale.h>
    {
        char *loc = setlocale(LC_ALL, "");
        log_result("setlocale(LC_ALL,'')", loc != NULL, loc);
    }

    printf("=== probe done ===\n");
    fflush(stdout);
    return 0;
}
