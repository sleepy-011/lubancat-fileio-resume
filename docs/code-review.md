# 独立代码审查与优化记录

本记录来自本次并行 AI 审查及主实现代理的交叉检查。审查对象是保存于 `review/v1/sparse_dl.c` 的初版；修复对象是 `src/sparse_dl.c`。未调用 DeepSeek 的内容不能标为 DeepSeek 输出。初版与修复版均已在鲁班猫 aarch64 实机运行同一套 16 项测试：初版暴露四类缺陷，修复版全部通过，详见文末的实际日志及计数说明。

## 发现 1：查询 FIFO 可能一直挂起

- **现象**：`mkfifo pipe.bin` 后执行 `./sparse-dl status pipe.bin` 或 `verify pipe.bin`，初版可能一直等待，而不是立即提示“必须为普通文件”。
- **根因**：`open_target()` 先执行阻塞的 `open(..., O_RDONLY)`，成功后才用 `fstat()` 判断文件类型；FIFO 没有写端时根本到不了类型判断。
- **修复**：打开目标时增加 `O_NONBLOCK`，再检查 `S_ISREG`。普通文件的常规 IO 不受该标志影响。
- **验证**：`test_fifo_and_symlink_are_rejected_without_hanging` 对真实 FIFO 执行三个命令，要求两秒内非零退出。测试同时检查目标符号链接被拒绝。

## 发现 2：状态记录解析不够严格

- **现象**：初版状态文件即使缺少末尾换行，也可通过解析；无符号 `scanf` 转换还可能接受带正负号的数字，超范围转换不能作为可靠输入校验。
- **根因**：`sscanf` 格式中的换行代表可匹配零个字符的空白；`SCNu64` 负责数值转换，不代表“只允许不带符号、未溢出的十进制字段”。
- **修复**：按格式逐字段读取十进制数字，转换前检查字符，通过 `strtoull` 与 `errno` 检查溢出，要求准确的字段分隔符和末尾换行，并保留设备号、inode、大小及进度上界校验。
- **验证**：`test_corrupted_and_noncanonical_states_are_rejected` 覆盖空文件、垃圾内容、缺失换行、尾随数据、NUL、负值、加号和超范围数字。每次同时检查 `status`、`resume` 拒绝，且目标内容没有被更改。`test_state_from_replaced_target_is_rejected` 检查替换为同大小但不同 inode 的目标会被拒绝。

## 发现 3：硬链接别名绕过手工修改限制

- **现象**：先完成 `resume target.bin`，执行 `ln target.bin alias.bin`，再执行 `write alias.bin 0 X`。初版只检查 `alias.bin.state`，因其不存在而允许写入，实际破坏了已有完成记录的 `target.bin`。
- **根因**：状态文件按路径命名；硬链接共享同一个 inode，却有不同的旁路状态文件名称。对每个操作加目标锁只能阻止同时运行，不能阻止这种先后执行的别名绕过。
- **修复**：需要独占修改的操作拒绝链接数不为 1 的目标。`status` 和 `verify` 的只读访问仍可保留。此限制是教学工具对合作进程的保护，不能阻止其他程序在外部直接修改文件。
- **验证**：`test_hardlink_alias_cannot_modify_managed_data` 创建真实硬链接，检查通过别名执行 `write`、`resume` 均被拒绝，最后完整校验原文件。

## 额外可靠性验证

额外发现 4：初版仅检查目标身份和大小，外部修改同一 inode 的已完成区域，或把进度从零改为大小内的更大值后，`resume` 可能直接报告完成。修复后的 `check_prefix()` 在续传前逐字节核对 `[0, done)` 的确定性内容，发现损坏即拒绝。`test_resume_rejects_corrupted_prefix_or_forged_progress` 分别复现伪造完整进度和同 inode 的已完成区内容损坏。校验恢复前缀会增加一次顺序读取成本，本项目 128 KiB 级文件可以接受。

- `write_all` 必须在短写后推进缓冲区指针，并在 `EINTR` 后重试。`tests/fault_io.c` 只拦截目标数据文件，真实注入短写和 `EINTR`；测试核对事件日志后再核对全部字节，避免没有注入却误称通过。
- 注入 `ENOSPC` 和零字节写入，确认命令非零退出、不会死循环、不会推进尚未落盘的数据进度；移除故障后再次续传并验证完整内容。
- 用真实子进程发送 `SIGINT`，读取持久化进度，核对前缀内容与未写区域全零，再检查重启打印的 `resume_from` 与进度一致。
- 完成后的每个字节均由 Python 独立生成预期值比较，再调用程序自己的 `verify`。这避免仅用程序自身的检查逻辑证明程序自己正确。
- Linux 集成测试通过 `python3 tests/test_cli.py ./sparse-dl` 或 `make check` 执行。必须在具备空洞文件支持的本地文件系统上运行；若缺少 C 编译器，故障注入测试会明确显示 `SKIP`，不能算作已经执行。
- 地址/未定义行为检测构建使用 `SPARSE_SKIP_FAULT_TESTS=1` 显式跳过三项 `LD_PRELOAD` 测试，避免与检测运行库的加载顺序冲突；其余 13 项仍执行。故障注入的完整验收必须在普通构建中另行完成，不能用这三项跳过记录代替。

## 明确的信任边界

状态文件绑定目标的设备号、inode 和大小，但没有密码学认证；恢复前的前缀校验检测与预期字节流不符的已完成内容，最终全量正确性仍通过 `verify` 验证。不能把该状态格式描述为能够发现所有篡改。程序使用 advisory lock，仅约束遵守相同加锁规则的进程。单次 Ctrl+C 恢复测试也不能替代对真实断电的硬件验证。

## 实测结果引用

已核对实际板端日志：[board-20261016-native-verification.log](../evidence/board-20261016-native-verification.log)。记录时间为北京时间 2026 年 10 月 16 日 01:18:58（日志 UTC 2026-10-15T17:18:58Z）。环境为 Linux 4.19.232、aarch64、Ubuntu 20.04.6 LTS、ext4、GCC 9.4.0。

严格编译选项包含 `-Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror`。`make check` 实测 **16 项通过、0 项失败、0 项跳过**，耗时 2.438 秒；日志结尾为 `BOARD_VERIFY_RESULT=PASS`。

初版实际对照日志：[board-20261016-baseline-regression.log](../evidence/board-20261016-baseline-regression.log)。初版原生编译退出码为 0；同一套 16 项测试运行 4.275 秒，测试退出码为 1，原始汇总为 `FAILED (failures=7, errors=1)`。

**这里的 7 是失败断言/子用例数，不是 7 个独立缺陷。** 其中状态格式测试有 5 个失败子用例：缺少末尾换行、设备号带加号、inode 带加号、大小带加号、进度为 `-0`；硬链接和伪造进度各产生 1 个失败断言；FIFO 等待超过 2 秒产生 1 个超时错误。合计涉及 4 个测试方法，对应四类缺陷；其余 12 个测试方法通过。

| 审查项 | 回归测试方法 | 初版板端结果 | 修复版板端结果 |
|---|---|---|---|
| FIFO 打开阻塞 | `test_fifo_and_symlink_are_rejected_without_hanging` | `status` 超时，1 个错误 | 通过 |
| 状态格式不严格 | `test_corrupted_and_noncanonical_states_are_rejected` | 5 个子用例失败 | 通过 |
| 硬链接绕过修改限制 | `test_hardlink_alias_cannot_modify_managed_data` | 别名写入被错误接受，1 个失败 | 通过 |
| 损坏前缀或伪造进度假完成 | `test_resume_rejects_corrupted_prefix_or_forged_progress` | 伪造完成进度被错误接受，1 个失败 | 通过 |

初版中前缀测试在第一个伪造进度断言处失败，后续“同 inode 外部修改”分支没有继续执行；该分支在修复版完整运行并通过。不能把一个方法的前半段失败记录描述为后半段也已执行。

短写与 `EINTR`、`ENOSPC`、零写入三项故障注入测试均实际执行并通过，没有跳过；测试本身会核对 `E/S/F/Z` 事件标记，未发生注入时不能通过。完整内容由独立预期值逐字节验证。

日志还记录了独立的 1 MiB 演示：创建后实际分配 0 字节；定点写入 12 字节后分配 4096 字节；真实发送 `SIGINT` 后进度保存为 4096，进程返回 130；重启打印 `resume_from=4096`，最终 `verified_bytes=1048576` 且状态进度为 100%。

上述两份证据是实际命令输出记录，不是原生终端截图。地址/未定义行为检测不包含在上述 16 项普通构建的通过结论中，执行后应另附独立日志。初版失败与修复版通过均有各自实机日志支持；不能把这些日志描述成 DeepSeek 调用证明。
