请逐节核对下面 README 与当前源码是否一致，指出命令参数、模拟下载范围、文件占用单位、恢复机制、测试与 AI 证据表述中的错误。真实测试和未执行测试要明确区分。只提出修改建议。

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

README：
# 基于文件 IO 的空洞文件断点续传模拟器

面向鲁班猫 1（RK3566 / Linux / aarch64）的 C 语言课程作业。实现创建空洞文件、`lseek + write` 定点写入、Ctrl+C 中断后续传，以及空间占用查询。数据源是本地确定性字节流：第 `n` 个字节为 `1 + n % 251`，偏移从 0 开始；这使最终内容可以独立校验。本程序没有 HTTP 请求功能。

## 1. 环境与构建

在开发板的 Linux 终端进入本目录，确认有 C 编译器、GNU Make；自动测试还需要 Python 3.7 或更高版本。

```sh
uname -a
uname -m
cc --version
make
make check
```

`make` 生成 `sparse-dl`，编译开启 C11、严格告警并将告警视作错误。普通构建的 `make check` 包含 16 个自动测试方法，其中 3 个使用 `LD_PRELOAD` 故障注入，需有可用 C 编译器。`make sanitize` 会重新构建并运行 AddressSanitizer / UndefinedBehaviorSanitizer 检查，需要目标编译器提供相应运行库；该配置执行其余 13 项，明确跳过上述 3 项，以避免预加载库与检测器冲突。测试数量描述的是当前测试配置，实际通过数须以执行报告为准。`make clean` 只删除可执行文件。

请选择支持稀疏文件的 Linux 文件系统，例如开发板上的 ext4。不同文件系统的块分配结果可以不同；以实际输出为准。板端验证结果及截图以 `evidence/` 中的真实材料为准，不能用本文命令示例代替运行证据。

2026-10-16 已在真实 `EmbedFire LubanCat-1` 上完成原生构建和验证：Ubuntu 20.04.6 LTS、Linux 4.19.232 / aarch64、ext4、Python 3.8.10、GCC 9.4.0。16 项自动测试全部通过，0 失败、0 错误、0 跳过；真实 SIGINT 后保存偏移 4096，以相同偏移恢复并校验全部 1048576 字节，`BOARD_VERIFY_RESULT=PASS`。程序功能、审查优化、板端测试与交付验证均已完成。详见 [板端实测报告](docs/board-test-report.md)、[截图索引](docs/board-screenshots.md) 和 [验证状态](docs/verification-status.md)。

## 2. 命令接口

所有数值参数均为十进制整数，单位是字节或毫秒；不接受 `128K`、负数、小数或超出有符号 64 位范围的值。

| 命令 | 用途与边界 |
|---|---|
| `./sparse-dl create FILE SIZE_BYTES` | 新建逻辑大小至少 131072 字节（128 KiB）的空洞文件；已有文件不会被覆盖 |
| `./sparse-dl write FILE OFFSET_BYTES TEXT` | 把命令行文本按原始字节写到指定偏移；不能超出文件逻辑大小 |
| `./sparse-dl status FILE` | 输出逻辑大小、已分配块数、实际占用、空间占比和保存的续传进度 |
| `./sparse-dl resume FILE [CHUNK_BYTES [DELAY_MS]]` | 按顺序生成并写入模拟数据；块大小 1～65536，默认 4096；延时 0～60000，默认 0 |
| `./sparse-dl verify FILE` | 逐字节验证整个文件是否等于确定性数据流，文件至少为 128 KiB |

`write` 使用字符串参数，不适合写入含 NUL 的任意二进制数据；多字节字符的长度按编码后的字节数计算。`resume` 从已保存偏移开始，首次运行从 0 开始，因此会覆盖其写入范围内先前手工写入的内容。续传状态文件已经存在后，`write` 会拒绝执行，以保持进度记录的含义。建议分别用两个新文件演示定点写入与续传。

正常完成返回 0；参数组合错误返回 2；其他报错一般返回 1。续传捕获 Ctrl+C（SIGINT）或 SIGTERM 后，若尚未完成则返回 130；如果信号到达时最后一块已完成，则仍返回 0。

## 3. 快速演示

在项目目录执行以下命令。`mktemp` 为本次演示创建新目录，避免覆盖已有文件。下面展示的是操作步骤，具体数字应以本次运行记录为准。

```sh
demo_dir=$(mktemp -d ./demo.XXXXXX)
./sparse-dl create "$demo_dir/holes.bin" 1048576
./sparse-dl status "$demo_dir/holes.bin"
./sparse-dl write "$demo_dir/holes.bin" 65536 HELLO
./sparse-dl status "$demo_dir/holes.bin"
od -An -tx1 -j 65532 -N 13 "$demo_dir/holes.bin"

./sparse-dl create "$demo_dir/resume.bin" 1048576
./sparse-dl resume "$demo_dir/resume.bin" 4096 100
# 写入若干块后按 Ctrl+C，等待程序返回终端。
./sparse-dl status "$demo_dir/resume.bin"
cat "$demo_dir/resume.bin.state"
./sparse-dl resume "$demo_dir/resume.bin" 65536
./sparse-dl verify "$demo_dir/resume.bin"
./sparse-dl status "$demo_dir/resume.bin"
```

观察要点：创建后逻辑大小已经是 1048576，但未写入部分仍为空洞；写入 `HELLO` 后仅局部需要分配数据块；Ctrl+C 后 `completed_offset` 应介于 0 和逻辑大小之间；再次 `resume` 输出的 `resume_from` 应等于该保存值；最终 `verify` 输出 `result=verified`。

## 4. 实现原理

### 空洞与定点写入

`create` 使用 `O_CREAT | O_EXCL` 新建文件，再以 `ftruncate` 设置逻辑长度，不循环写零。空洞区域读取时返回零。`write` 使用 `lseek(fd, offset, SEEK_SET)` 和循环 `write`，只提交指定文本范围；文件系统仍按数据块分配空间，因此写入 5 字节可能增加一个或更多分配块。程序不使用 `O_APPEND`，并检查写入范围避免意外扩大文件。[ftruncate 手册](https://man7.org/linux/man-pages/man2/ftruncate.2.html)、[lseek 手册](https://man7.org/linux/man-pages/man2/lseek.2.html)、[write 手册](https://man7.org/linux/man-pages/man2/write.2.html)。

### 进度与恢复

逻辑大小在创建时已经确定，不能当作已下载长度。`FILE.state` 保存格式版本、设备号、inode、逻辑大小和连续完成偏移。设备号、inode 及大小用于拒绝明显属于其他目标的状态文件；严格解析拒绝负号、溢出、缺少结束换行及尾部垃圾。一个偏移仅表示 `[0, done)` 已连续完成，不能表示乱序下载的多个区间。恢复前会逐字节校验这个已完成前缀，发现内容损坏即报错，而不会直接信任进度；此检查耗时与前缀长度成正比。

每块处理顺序为：生成数据 → 定位并完整写入 → `fsync` 数据文件 → 更新内存偏移 → 写临时状态文件并 `fsync` → 同目录 `rename` 替换正式状态 → `fsync` 父目录。检查点落后于数据时，重启可能重新写入最后一块；确定性数据使重复写入结果一致。状态更新不会故意超前于数据。[fsync 手册](https://man7.org/linux/man-pages/man2/fsync.2.html)、[rename 手册](https://man7.org/linux/man-pages/man2/rename.2.html)。

信号处理函数只设置 `sig_atomic_t` 标志。主循环完成当前块与检查点后退出。`write_all` 处理部分写入与 `EINTR`，避免把一次 `write` 的返回值误认为已完成整个缓冲区。

### 空间统计

`logical_bytes` 来自 `st_size`；`allocated_blocks_512` 来自 `st_blocks`，每单位为 512 字节；`allocated_bytes = st_blocks × 512`；`space_percent = allocated_bytes / logical_bytes × 100%`。这里的 512 不能替换成文件系统最佳 IO 大小 `st_blksize`。空间占比是分配空间的度量，与 `progress_percent` 表达的续传进度不同。[inode 手册](https://man7.org/linux/man-pages/man7/inode.7.html)。

程序使用非阻塞 `flock`：修改操作持有排他锁，查询和验证持有共享锁；忙碌时直接报错。修改操作拒绝链接数不为 1 的目标，防止硬链接别名绕过配套状态检查；只读查询和验证允许硬链接。打开目标时使用非阻塞模式，再检查普通文件类型，避免 FIFO 导致无限等待。这是协作式锁，不阻止不遵守该锁的其他程序修改文件。

## 5. 测试与审查材料

- [测试计划](docs/test-plan.md)：功能、边界、完整性与中断恢复验收。
- [验证状态](docs/verification-status.md)：已完成的编译、板端运行、截图和最终归档进度。
- [板端实测报告](docs/board-test-report.md)：真实设备、16 项通过结果、空洞和中断恢复的实测数据。
- [截图索引](docs/board-screenshots.md)：四组真实板端终端截图及其采集说明。
- [作业完成过程记录](docs/作业完成过程记录.txt)：按任务分析、实现、审查、测试和归档顺序记录实际完成过程。
- [GPT 使用记录](docs/gpt-usage-record.md)：本次 GPT/Codex 的实际使用过程、提示词、输出与采纳判断。
- [AI 协作日志](docs/ai-collaboration-log.md)：实际使用范围、任务指令、采纳判断及审查记录。
- [代码审查](docs/code-review.md)：真实缺陷、修复与回归验证；初版保存在 `review/v1/`。
- [课堂分享](docs/class-share.md)：约 4 分钟讲稿和演示步骤。
- [提交清单](docs/submission-checklist.md)：评分映射与材料核查。

具体已执行测试、板端系统信息、运行输出与截图请查看 `evidence/`。文档中的计划不表示测试已经通过；只有实际报告中列明的项目可视为完成。

板端可执行 `bash scripts/board_verify.sh` 一次采集环境、构建、测试和真实 SIGINT 续传演示的日志。源码包由 `python3 scripts/package.py` 生成；附本次实际本机检查记录的交付包由 `python3 scripts/package_submission.py` 生成。

## 6. 范围和限制

本项目演示 Linux 文件 IO 的续传机制，支持可捕获信号后恢复；没有执行真实网络下载，也没有宣称通过突然断电恢复认证。虽然加入了同步和原子检查点，但硬件、挂载参数、文件系统及存储设备行为仍影响掉电后的持久性。恢复前缀校验和最终 `verify` 可以发现不符合数据规则的内容，但不能阻止其他程序绕过锁持续篡改文件；应保留目标及配套状态文件，避免手工编辑进度。

每块都同步数据与状态，侧重正确性而非吞吐量。更大的块可以减少同步次数，但增加单次中断等待及可能重复写入的数据量。状态异常时选择报错，不自动猜测进度。修复状态或更换目标之前应保留现场，重新创建新目标是最明确的重新开始方式。

## 7. 作业要求与来源说明

截图要求提交源码、Makefile、README、AI 协作日志和板端运行截图，并于第 7 周周五上课前提交、课堂分享；具体公历日期需要按课程教学周历核对。原图列出 DeepSeek；按用户本轮补充要求，本次 AI 材料采用真实的 GPT/Codex 使用记录，明确注明工具替代，不将其标为 DeepSeek 输出。提示词、处理结果、采纳判断及初版修复证据分别保存在 GPT 使用记录、协作日志和审查目录。DeepSeek 脚本仅作为可选扩展，不列为本次交付的待办。

