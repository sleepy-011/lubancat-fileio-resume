# 鲁班猫板端实测报告

**结论：真实鲁班猫原生构建成功，16 项自动测试全部通过，无跳过；空洞、定点写入和 SIGINT 后续传演示通过。四组原生终端截图已齐备。** 本报告保留主日志结果，截图另见 [截图索引](board-screenshots.md)。

执行日期为北京时间 **2026-10-16**。原始日志记录 `2026-10-15T17:18:58Z`，换算为 Asia/Shanghai 是 **2026-10-16 01:18:58**。

## 环境与证据

| 项目 | 实际记录 |
|---|---|
| 设备树型号 | EmbedFire LubanCat-1 |
| 主机与架构 | lubancat，aarch64 |
| 操作系统 | Ubuntu 20.04.6 LTS |
| 内核 | Linux 4.19.232 |
| 文件系统 | ext4，`/dev/mmcblk1p3`，挂载于 `/` |
| 编译器 | GCC / cc 9.4.0 |
| 测试运行时 | Python 3.8.10 |
| 执行入口 | `bash scripts/board_verify.sh` |
| 脚本结果 | `BOARD_VERIFY_RESULT=PASS` |

原始命令输出：[board-20261016-native-verification.log](../evidence/board-20261016-native-verification.log)。机器可读摘要：[board-20261016-results.json](../evidence/board-20261016-results.json)。执行通过主机身份已核对的 SSH 连接完成，项目位于新建的独立目录；没有用 Windows 交叉编译代替本次 Linux 原生构建。

板端最终源码 SHA-256 与本机交叉编译版本一致：

```text
cfb0c80b73b0dff620ff79a9c3d91881088acdbacf25d973e96699e44c6fdb21
```

原生构建采用 `-std=c11 -Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror`，编译成功后运行 `python3 tests/test_cli.py ./sparse-dl`。

## 自动测试结果

日志汇总为 `Ran 16 tests in 2.438s`、`OK`，**通过 16，失败 0，错误 0，跳过 0**。下表每行对应一个实际测试方法，结果均来自日志中的 `ok`。

| 实际测试方法 | 验证重点 | 结果 |
|---|---|---|
| `test_create_is_sparse_and_status_matches_stat` | 稀疏创建、统计与系统 stat 对照 | 通过 |
| `test_create_refuses_small_existing_or_orphan_state` | 尺寸下限、拒绝覆盖及孤立状态 | 通过 |
| `test_positioned_write_leaves_all_other_bytes_zero` | 定点内容正确，其他区域保持零 | 通过 |
| `test_invalid_arguments_and_ranges_do_not_mutate_target` | 非法参数及越界不改动目标 | 通过 |
| `test_resume_and_verify_non_chunk_multiple` | 非整块尾部、完整内容与完成后恢复 | 通过 |
| `test_sigint_checkpoints_and_resumes_in_real_process` | 真实子进程 SIGINT、保存偏移与恢复 | 通过 |
| `test_corrupted_and_noncanonical_states_are_rejected` | 严格拒绝坏状态和非规范记录 | 通过 |
| `test_state_from_replaced_target_is_rejected` | 拒绝其他 inode 的状态 | 通过 |
| `test_existing_lock_blocks_read_and_write_commands` | 协作锁冲突下拒绝并发操作 | 通过 |
| `test_fifo_and_symlink_are_rejected_without_hanging` | FIFO 不挂起，目标符号链接拒绝 | 通过 |
| `test_hardlink_alias_cannot_modify_managed_data` | 硬链接别名不能绕过修改限制 | 通过 |
| `test_verify_detects_actual_content_corruption` | 全量验证发现真实内容损坏 | 通过 |
| `test_resume_rejects_corrupted_prefix_or_forged_progress` | 拒绝损坏前缀和伪造进度 | 通过 |
| `test_short_write_and_eintr_are_retried` | 真实注入短写和 EINTR，重试后内容正确 | 通过 |
| `test_write_failure_preserves_checkpoint_and_can_restart` | ENOSPC 不推进错误进度，解除故障后可恢复 | 通过 |
| `test_zero_write_fails_without_infinite_loop` | 零字节写入失败退出，不死循环 | 通过 |

最后 3 项在本次普通构建中真实执行，没有通过检测器配置跳过。`make sanitize` 是单独的可选配置，本报告没有将其标为已执行。

## 空洞与定点写入演示

| 阶段 | 逻辑大小 | 512 字节分配单位数 | 实际占用 | 空间占比 |
|---|---:|---:|---:|---:|
| 新建空洞文件 | 1048576 | 0 | 0 | 0.000% |
| 偏移 65536 写入 12 字节后 | 1048576 | 8 | 4096 | 0.391% |

实测说明创建没有写满全部数据区域；小范围写入后按文件系统块分配，逻辑长度保持不变。定点写入保护其他区域的逐字节检查由上述自动测试独立完成。本文数据是本次 ext4 的结果，不要求其他文件系统的分配数字完全相同。

截图 02 使用另一新文件写入 `HELLO`（5 字节），实际占用同为 4096 字节；主日志写入的是 12 字节。这是两次真实演示，不能把字节数混为同一次操作。

## SIGINT 后恢复演示

1. 新建逻辑大小 1048576 字节的独立目标，首次续传以块大小 4096、延时 100 ms 运行。
2. 脚本观察到真实提交的检查点后发送 SIGINT。程序输出 `completed_offset=4096`、`result=interrupted`，退出码 130；状态记录末字段为 4096。
3. `status` 显示完成偏移 4096，进度 0.391%。再次续传使用块大小 65536，输出 `resume_from=4096`，与保存偏移相同。
4. 最终偏移为 1048576，`result=complete`，退出码 0。
5. 全量校验输出 `verified_bytes=1048576`、`result=verified`，退出码 0；最终进度和本次实际空间占比均为 100.000%。

演示输出包括 `RESUME_DEMO_RESULT=PASS`，总验证输出包括 `BOARD_VERIFY_RESULT=PASS`。此处采用实际 SIGINT，等效于 Ctrl+C 所产生的中断信号；没有假装存在人工按键录像。

## 结论边界与剩余材料

四处真实初版缺陷对应的 FIFO、状态解析、硬链接及损坏前缀回归在本次板端全部通过；详见 `docs/code-review.md` 和保留的初版差异。真实日志、结构化结果和四组原生截图已齐备，源码归档新目录重建已通过，完整证据包附 SHA-256 清单。

截图通过 `xwd` 捕获开发板原生 X11 终端窗口，`ffmpeg` 仅执行 PNG 格式转换，没有绘制、拼接或改写内容。采集元数据见 `evidence/board-20261016-screenshots.json`。截图 01 为再次实际执行的 16 项通过结果，耗时 2.404 秒；本文主日志运行耗时 2.438 秒。截图 03 / 04 的检查点和恢复起点仍均为 4096，最终校验仍为 1048576 字节。

本次验证不包含硬件突然断电、故障存储、绕过协作锁持续篡改、真实 HTTP 或乱序并行下载，不能从上述结果推导这些额外保证。测试计划中的 20 个场景是验收设计，不等于额外执行了 20 个独立测试方法。

## 源码归档复现

已将交付源码压缩包传入开发板，解压至新的独立目录并执行 `make`。原生构建退出 0；随后创建 131072 字节文件、续传及 verify 均退出 0。记录为 `evidence/board-20261016-release-check.json`。最终交付包的 Makefile、C 源码、测试及脚本哈希与该次重建记录一致；之后仅补充结果说明和证据。
