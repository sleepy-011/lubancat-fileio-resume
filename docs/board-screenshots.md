# 真实板端截图索引

四组截图均来自真实鲁班猫 LubanCat-1 的原生 X11 终端窗口，已由主代理逐张检查文字清晰和内容完整。使用 `xwd` 采集窗口像素，`ffmpeg` 仅将格式转换为 PNG；未绘制、拼接或改写终端内容。每张图片为 1544 × 1200 像素。

采集发生于北京时间 2026-10-16 01:27:36～01:27:44。元数据中的 UTC 日期为 2026-10-15，是同一时刻。原始窗口标识、采集时间及执行命令保存在 [screenshots.json](../evidence/board-20261016-screenshots.json)。

| 截图 | 打开原图 | 展示事实 |
|---|---|---|
| 01 环境与测试 | [environment-tests.png](../evidence/board-20261016-01-environment-tests.png) | 真实主机、aarch64、设备型号、编译器、Python、ext4，`make check` 再次执行 16 项全部通过，耗时 2.404 秒 |
| 02 空洞与定点写入 | [sparse-write.png](../evidence/board-20261016-02-sparse-write.png) | 1 MiB 空洞初始分配为 0；在 65536 写入 HELLO（5 字节）后占用 4096 字节；十六进制显示前后零及目标文本 |
| 03 真实中断与检查点 | [interrupt-checkpoint.png](../evidence/board-20261016-03-interrupt-checkpoint.png) | 向实际续传进程发送 SIGINT，退出 130，完成偏移 4096，显示保存状态记录 |
| 04 恢复与全量验证 | [resume-verified.png](../evidence/board-20261016-04-resume-verified.png) | `resume_from=4096` 与保存值一致，最终 1048576 字节完成，`result=verified`，进度 100% |

主验证日志运行耗时为 2.438 秒，截图 01 为另一次运行耗时 2.404 秒；主日志定点演示写入 12 字节，截图 02 为另一次演示写入 5 字节。它们均为真实执行，不能将两次操作的数值混用。截图 03 / 04 的中断使用脚本发送 SIGINT，等效于 Ctrl+C 的信号，并未声称有人工按键录像。

本次原生构建、测试、功能演示和截图材料已完成，源码归档新目录重建已通过，完整证据包附 SHA-256 清单。详细环境与测试结果见 [板端实测报告](board-test-report.md)。课堂分享仍由学生按课程安排完成。
