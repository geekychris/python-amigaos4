/*
 * tests/test_amiga_shim_boundary.c — boundary tests for amiga_to_posix_path()
 *
 * Tests converted path buffer bounds of exactly 1023 and 1024 bytes.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <strings.h>

/* Standalone function declaration matching amiga_to_posix_path */
const char *amiga_to_posix_path(const char *path, char *buf, size_t buflen);

int main(void)
{
    printf("=== Testing amiga_to_posix_path boundary limits ===\n");
    int failures = 0;

    char buf[1024];

    /* Case A: Converted path length of exactly 1023 chars (/python3/ + 1014 'a's) */
    char path1023[2048];
    strcpy(path1023, "python3:");
    memset(path1023 + 8, 'a', 1014);
    path1023[8 + 1014] = '\0';

    memset(buf, 0, sizeof(buf));
    errno = 0;
    const char *res1 = amiga_to_posix_path(path1023, buf, 1024);
    if (!res1) {
        printf("FAIL: Case A (1023 bytes) returned NULL (errno=%d)\n", errno);
        failures++;
    } else if (res1 != buf) {
        printf("FAIL: Case A (1023 bytes) did not return buf\n");
        failures++;
    } else if (strlen(buf) != 1023) {
        printf("FAIL: Case A (1023 bytes) output length is %zu, expected 1023\n", strlen(buf));
        failures++;
    } else {
        printf("PASS: Case A (1023 bytes converted path fits in 1024-byte buffer)\n");
    }

    /* Case B: Converted path length of exactly 1024 chars (/python3/ + 1015 'a's) */
    char path1024[2048];
    strcpy(path1024, "python3:");
    memset(path1024 + 8, 'a', 1015);
    path1024[8 + 1015] = '\0';

    memset(buf, 0, sizeof(buf));
    errno = 0;
    const char *res2 = amiga_to_posix_path(path1024, buf, 1024);
    if (res2 != NULL) {
        printf("FAIL: Case B (1024 bytes) expected NULL, got non-NULL\n");
        failures++;
    } else if (errno != ENAMETOOLONG) {
        printf("FAIL: Case B (1024 bytes) expected errno ENAMETOOLONG (%d), got %d\n", ENAMETOOLONG, errno);
        failures++;
    } else {
        printf("PASS: Case B (1024 bytes converted path fails with ENAMETOOLONG)\n");
    }

    if (failures == 0) {
        printf("ALL BOUNDARY TESTS PASSED!\n");
        return 0;
    } else {
        printf("%d BOUNDARY TEST FAILURES!\n", failures);
        return 1;
    }
}
