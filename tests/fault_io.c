#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/* Test-only shim. Affect write() on FAULT_TARGET, never checkpoint files.
 * FAULT_MODE=retry: alternate EINTR and a real short write.
 * FAULT_MODE=fail: simulate ENOSPC. FAULT_MODE=zero: return zero.
 * FAULT_LOG records evidence that injection actually ran: E/S/F/Z. */
static ssize_t (*real_write)(int, const void *, size_t);
static unsigned long calls;

static void event(char c)
{
    const char *path = getenv("FAULT_LOG");
    if (path) {
        int fd = open(path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0600);
        if (fd >= 0) {
            (void)real_write(fd, &c, 1);
            (void)close(fd);
        }
    }
}

ssize_t write(int fd, const void *buffer, size_t count)
{
    char descriptor[64], path[PATH_MAX + 1];
    const char *target = getenv("FAULT_TARGET");
    const char *mode = getenv("FAULT_MODE");
    ssize_t length;
    if (!real_write) {
        void *symbol = dlsym(RTLD_NEXT, "write");
        if (!symbol)
            _exit(125);
        memcpy(&real_write, &symbol, sizeof real_write);
    }
    if (!target || !mode || !count)
        return real_write(fd, buffer, count);
    (void)snprintf(descriptor, sizeof descriptor, "/proc/self/fd/%d", fd);
    length = readlink(descriptor, path, sizeof path - 1);
    if (length < 0)
        return real_write(fd, buffer, count);
    path[(size_t)length] = '\0';
    if (strcmp(path, target) != 0)
        return real_write(fd, buffer, count);
    if (strcmp(mode, "fail") == 0) {
        event('F');
        errno = ENOSPC;
        return -1;
    }
    if (strcmp(mode, "zero") == 0) {
        event('Z');
        return 0;
    }
    if (strcmp(mode, "retry") == 0) {
        ++calls;
        if (calls % 2) {
            event('E');
            errno = EINTR;
            return -1;
        }
        if (count > 1) {
            event('S');
            return real_write(fd, buffer, count / 2);
        }
    }
    return real_write(fd, buffer, count);
}
