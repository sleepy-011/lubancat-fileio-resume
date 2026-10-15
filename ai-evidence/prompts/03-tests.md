请针对附件程序提出可执行的 CLI 黑盒测试，包括空洞占用、定点写入、Ctrl+C 和 SIGKILL 恢复、损坏状态、越界、锁冲突、符号链接、最终内容校验。将预期与实际区分，不要声称已经运行测试。

当前源码：
```c
#define _GNU_SOURCE
#define _FILE_OFFSET_BITS 64
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* Linux/aarch64 teaching project. The source is a deterministic byte stream,
 * not an HTTP server: byte at position n is 1 + n % 251. */
#define MIN_SIZE UINT64_C(131072)
#define BUFFER_SIZE 65536U
static volatile sig_atomic_t stopping = 0;

static void die(const char *message)
{
    fprintf(stderr, "error: %s\n", message);
    exit(EXIT_FAILURE);
}

static void fail(const char *operation)
{
    perror(operation);
    exit(EXIT_FAILURE);
}

static void on_signal(int signo)
{
    (void)signo;
    stopping = 1; /* No stdio, allocation, or state-file writes in the handler. */
}

static uint64_t number(const char *text)
{
    char *end = NULL;
    unsigned long long value;
    if (text[0] < '0' || text[0] > '9')
        die("expected a nonnegative decimal integer (bytes)");
    errno = 0;
    value = strtoull(text, &end, 10);
    if (errno || !end || *end || value > (unsigned long long)INT64_MAX)
        die("integer is invalid or exceeds signed 64-bit range");
    return (uint64_t)value;
}

static char *state_name(const char *path)
{
    size_t n = strlen(path);
    char *result = malloc(n + sizeof ".state");
    if (!result)
        fail("malloc");
    memcpy(result, path, n);
    memcpy(result + n, ".state", sizeof ".state");
    return result;
}

static void sync_fd(int fd)
{
    while (fsync(fd) < 0) {
        if (errno != EINTR)
            fail("fsync");
    }
}

static void write_all(int fd, const void *buffer, size_t count)
{
    const unsigned char *p = buffer;
    while (count) {
        ssize_t n = write(fd, p, count);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            fail("write");
        }
        if (!n)
            die("write made no progress");
        p += (size_t)n;
        count -= (size_t)n;
    }
}

static void seek_to(int fd, uint64_t offset)
{
    if (lseek(fd, (off_t)offset, SEEK_SET) == (off_t)-1)
        fail("lseek");
}

static int open_target(const char *path, int flags, struct stat *st, int exclusive)
{
    /* Do not block on a FIFO before fstat can reject non-regular files. */
    int fd = open(path, flags | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0)
        fail("open target");
    if (flock(fd, (exclusive ? LOCK_EX : LOCK_SH) | LOCK_NB) < 0)
        die("target is busy (another command holds the advisory lock)");
    if (fstat(fd, st) < 0)
        fail("fstat target");
    if (!S_ISREG(st->st_mode) || st->st_size < 0)
        die("target must be a regular file");
    if (exclusive && st->st_nlink != 1)
        die("modifying a target with hard-link aliases is not supported");
    return fd;
}

static uint64_t state_integer(const char **cursor, char separator)
{
    const char *start = *cursor;
    char *end;
    unsigned long long value;
    if (*start < '0' || *start > '9')
        die("invalid state integer");
    errno = 0;
    value = strtoull(start, &end, 10);
    if (errno || *end != separator)
        die("invalid or overflowing state integer");
    *cursor = end + 1;
    return (uint64_t)value;
}

static void sync_parent(const char *path)
{
    char *copy = strdup(path);
    char *slash;
    int dir;
    if (!copy)
        fail("strdup");
    slash = strrchr(copy, '/');
    if (!slash) {
        free(copy);
        copy = strdup(".");
        if (!copy)
            fail("strdup");
    } else if (slash == copy) {
        slash[1] = '\0';
    } else {
        *slash = '\0';
    }
    dir = open(copy, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (dir < 0)
        fail("open parent directory");
    sync_fd(dir);
    if (close(dir) < 0)
        fail("close directory");
    free(copy);
}

static uint64_t load_state(const char *state, const struct stat *st, int *exists)
{
    char buffer[256];
    size_t used = 0;
    uint64_t dev, ino, size, done;
    const char *cursor;
    int fd = open(state, O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    struct stat ss;
    *exists = 0;
    if (fd < 0) {
        if (errno == ENOENT)
            return 0;
        fail("open state");
    }
    if (fstat(fd, &ss) < 0)
        fail("fstat state");
    if (!S_ISREG(ss.st_mode))
        die("state must be a regular file");
    for (;;) {
        ssize_t n = read(fd, buffer + used, sizeof buffer - 1U - used);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            fail("read state");
        }
        if (!n)
            break;
        used += (size_t)n;
        if (used == sizeof buffer - 1U)
            die("state is too long");
    }
    if (close(fd) < 0)
        fail("close state");
    buffer[used] = '\0';
    if (used < sizeof "SPARSE_DL_V1 " - 1U ||
        memcmp(buffer, "SPARSE_DL_V1 ", sizeof "SPARSE_DL_V1 " - 1U) != 0)
        die("invalid state header");
    cursor = buffer + sizeof "SPARSE_DL_V1 " - 1U;
    dev = state_integer(&cursor, ' ');
    ino = state_integer(&cursor, ' ');
    size = state_integer(&cursor, ' ');
    done = state_integer(&cursor, '\n');
    if ((size_t)(cursor - buffer) != used || done > size ||
        dev != (uint64_t)st->st_dev || ino != (uint64_t)st->st_ino ||
        size != (uint64_t)st->st_size)
        die("invalid state or state belongs to a different target");
    *exists = 1;
    return done;
}

static void check_prefix(int fd, uint64_t length)
{
    unsigned char buffer[BUFFER_SIZE];
    uint64_t position = 0;
    seek_to(fd, 0);
    while (position < length) {
        uint64_t left = length - position;
        size_t want = left < BUFFER_SIZE ? (size_t)left : BUFFER_SIZE;
        ssize_t n = read(fd, buffer, want);
        if (n < 0) {
            if (errno == EINTR)
                continue;
            fail("read verify");
        }
        if (!n)
            die("unexpected EOF while checking downloaded data");
        for (size_t i = 0; i < (size_t)n; ++i) {
            if (buffer[i] != (unsigned char)(1U + (position + (uint64_t)i) % 251U)) {
                fprintf(stderr, "error: content mismatch at offset=%" PRIu64 "\n",
                        position + (uint64_t)i);
                exit(EXIT_FAILURE);
            }
        }
        position += (uint64_t)n;
    }
}

static void save_state(const char *state, const struct stat *st, uint64_t done)
{
    char record[256];
    size_t n = strlen(state);
    char *temporary = malloc(n + sizeof ".tmp.XXXXXX");
    int fd, length;
    if (!temporary)
        fail("malloc");
    memcpy(temporary, state, n);
    memcpy(temporary + n, ".tmp.XXXXXX", sizeof ".tmp.XXXXXX");
    fd = mkstemp(temporary); /* Same directory: rename remains atomic. */
    if (fd < 0)
        fail("mkstemp state");
    length = snprintf(record, sizeof record,
                      "SPARSE_DL_V1 %" PRIu64 " %" PRIu64 " %" PRIu64
                      " %" PRIu64 "\n", (uint64_t)st->st_dev,
                      (uint64_t)st->st_ino, (uint64_t)st->st_size, done);
    if (length < 0 || (size_t)length >= sizeof record)
        die("state record overflow");
    write_all(fd, record, (size_t)length);
    sync_fd(fd);
    if (close(fd) < 0)
        fail("close temporary state");
    if (rename(temporary, state) < 0)
        fail("rename state");
    sync_parent(state);
    free(temporary);
}

static void create_target(const char *path, uint64_t size)
{
    char *state = state_name(path);
    struct stat st;
    int fd;
    if (size < MIN_SIZE)
        die("create size must be at least 131072 bytes (128 KiB)");
    if (lstat(state, &st) == 0)
        die("state path already exists; choose a new target name");
    if (errno != ENOENT)
        fail("check state path");
    fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0)
        fail("create target (existing files are never overwritten)");
    if (flock(fd, LOCK_EX | LOCK_NB) < 0)
        fail("lock new target");
    if (ftruncate(fd, (off_t)size) < 0)
        fail("ftruncate");
    sync_fd(fd);
    sync_parent(path);
    if (close(fd) < 0)
        fail("close target");
    printf("created=%s\nlogical_bytes=%" PRIu64 "\n", path, size);
    free(state);
}

static void write_target(const char *path, uint64_t offset, const char *text)
{
    struct stat st, ss;
    char *state = state_name(path);
    size_t count = strlen(text);
    int fd = open_target(path, O_RDWR, &st, 1);
    if (lstat(state, &ss) == 0)
        die("manual write is disabled once resume state exists");
    if (errno != ENOENT)
        fail("check state path");
    if (offset > (uint64_t)st.st_size ||
        (uint64_t)count > (uint64_t)st.st_size - offset)
        die("write range exceeds logical size");
    seek_to(fd, offset);
    write_all(fd, text, count);
    sync_fd(fd);
    if (close(fd) < 0)
        fail("close target");
    printf("written_offset=%" PRIu64 "\nwritten_bytes=%zu\n", offset, count);
    free(state);
}

static void print_status(const char *path)
{
    struct stat st;
    char *state = state_name(path);
    int exists;
    int fd = open_target(path, O_RDONLY, &st, 0);
    uint64_t done = load_state(state, &st, &exists);
    double allocated = (double)st.st_blocks * 512.0;
    printf("logical_bytes=%" PRIu64 "\nallocated_blocks_512=%" PRIu64
           "\nallocated_bytes=%.0f\nspace_percent=%.3f\nstate_exists=%d\n"
           "completed_offset=%" PRIu64 "\nprogress_percent=%.3f\n",
           (uint64_t)st.st_size, (uint64_t)st.st_blocks, allocated,
           st.st_size ? allocated * 100.0 / (double)st.st_size : 0.0,
           exists, done, st.st_size ? (double)done * 100.0 / (double)st.st_size : 0.0);
    if (close(fd) < 0)
        fail("close target");
    free(state);
}

static int resume_target(const char *path, size_t chunk, uint64_t delay_ms)
{
    unsigned char buffer[BUFFER_SIZE];
    struct stat st;
    struct sigaction action;
    char *state = state_name(path);
    int exists;
    int fd = open_target(path, O_RDWR, &st, 1); /* Never O_TRUNC. */
    uint64_t done = load_state(state, &st, &exists);
    uint64_t size = (uint64_t)st.st_size;
    if (size < MIN_SIZE)
        die("resume target must be at least 128 KiB");
    memset(&action, 0, sizeof action);
    action.sa_handler = on_signal;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) < 0 ||
        sigaction(SIGTERM, &action, NULL) < 0)
        fail("sigaction");
    setvbuf(stdout, NULL, _IOLBF, 0);
    check_prefix(fd, done);
    if (!exists)
        save_state(state, &st, 0);
    printf("resume_from=%" PRIu64 "\n", done);
    while (done < size && !stopping) {
        size_t n = (size - done < (uint64_t)chunk) ? (size_t)(size - done) : chunk;
        for (size_t i = 0; i < n; ++i)
            buffer[i] = (unsigned char)(1U + (done + (uint64_t)i) % 251U);
        seek_to(fd, done);
        write_all(fd, buffer, n);
        sync_fd(fd); /* Data must be durable before advancing the checkpoint. */
        done += (uint64_t)n;
        save_state(state, &st, done);
        printf("completed_offset=%" PRIu64 "\n", done);
        if (delay_ms && done < size && !stopping) {
            struct timespec pause = {(time_t)(delay_ms / 1000U),
                                     (long)((delay_ms % 1000U) * 1000000U)};
            while (nanosleep(&pause, &pause) < 0 && errno == EINTR && !stopping) {
                /* Preserve the remaining delay except when asked to stop. */
            }
        }
    }
    if (close(fd) < 0)
        fail("close target");
    free(state);
    printf("result=%s\n", done == size ? "complete" : "interrupted");
    return done == size ? 0 : 130;
}

static void verify_target(const char *path)
{
    struct stat st;
    int fd = open_target(path, O_RDONLY, &st, 0);
    uint64_t size = (uint64_t)st.st_size;
    if (size < MIN_SIZE)
        die("unexpected target length");
    check_prefix(fd, size);
    if (close(fd) < 0)
        fail("close target");
    printf("verified_bytes=%" PRIu64 "\nresult=verified\n", size);
}

static void usage(const char *program)
{
    fprintf(stderr,
            "Sparse file resumable download simulator (Linux)\n"
            "Usage:\n  %s create FILE SIZE_BYTES\n"
            "  %s write FILE OFFSET_BYTES TEXT\n"
            "  %s status FILE\n"
            "  %s resume FILE [CHUNK_BYTES [DELAY_MS]]\n"
            "  %s verify FILE\n"
            "SIZE >= 131072; CHUNK 1..65536 (default 4096); DELAY 0..60000.\n",
            program, program, program, program, program);
}

int main(int argc, char **argv)
{
    if (argc == 4 && strcmp(argv[1], "create") == 0)
        create_target(argv[2], number(argv[3]));
    else if (argc == 5 && strcmp(argv[1], "write") == 0)
        write_target(argv[2], number(argv[3]), argv[4]);
    else if (argc == 3 && strcmp(argv[1], "status") == 0)
        print_status(argv[2]);
    else if (argc >= 3 && argc <= 5 && strcmp(argv[1], "resume") == 0) {
        uint64_t chunk = argc >= 4 ? number(argv[3]) : 4096;
        uint64_t delay = argc == 5 ? number(argv[4]) : 0;
        if (!chunk || chunk > BUFFER_SIZE || delay > 60000)
            die("chunk must be 1..65536 bytes; delay must be 0..60000 ms");
        return resume_target(argv[2], (size_t)chunk, delay);
    } else if (argc == 3 && strcmp(argv[1], "verify") == 0)
        verify_target(argv[2]);
    else {
        usage(argv[0]);
        return 2;
    }
    return 0;
}

```

