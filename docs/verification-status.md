# 当前交付与验证状态

记录更新日期：2026-10-16（Asia/Shanghai）。本文件区分源码交付、编译检查、网络连接状态与实际板端运行。

## 已完成

- `create / write / resume / status / verify` 五个命令、Makefile。
- 16 项 Linux 集成测试方法，包含真实子进程 SIGINT、逐字节内容比较与 3 项故障注入。
- 4 处真实初版缺陷的独立审查与修复；保留初版、实际差异和回归用例。
- 中文 README、GPT 使用记录、8 次真实独立指令的协作记录、测试计划、课堂分享与答辩准备。
- 按用户补充要求，AI 部分使用本次真实 GPT/Codex 协作记录；另保留可选 DeepSeek 脚本，未调用。
- 板端一键验证脚本，会采集真实环境、执行测试、演示空洞和 SIGINT 后续传并保存输出。
- 真实鲁班猫原生构建及 16 项集成测试全部通过，0 跳过；空洞、定点写入和 SIGINT 后续传演示通过。
- 四组真实板端原生终端截图已采集，主代理已逐张检查清晰度和内容完整性，索引见 `docs/board-screenshots.md`。
- 源码压缩包、逐文件 SHA-256 清单与压缩包校验值。

## 本机已执行的检查

执行主机为 Windows。已使用官方 Zig 0.14.1 进行交叉编译，开启 C11、严格警告并将警告视为错误。下载的编译器 SHA-256 已与官方发布索引核对。

| 构建对象 | 结果 |
|---|---|
| 修复版 Linux aarch64 / musl | 退出 0 |
| 修复版 Linux x86_64 / musl | 退出 0 |
| 审查初版 Linux x86_64 / musl | 退出 0 |
| 故障注入库 Linux x86_64 / musl | 退出 0 |
| 修复版 Linux aarch64 / GNU libc | 退出 0 |
| 故障注入库 Linux aarch64 / GNU libc | 退出 0 |

原始记录：`evidence/cross-build-20261015T052638Z.log`。修复版源码 SHA-256：

```text
cfb0c80b73b0dff620ff79a9c3d91881088acdbacf25d973e96699e44c6fdb21
```

另外已执行 Python 脚本语法检查、Bash 脚本语法检查，以及源码包的 ZIP/tar 负载和逐文件哈希校验。最终本机复核记录见 `evidence/local-verification.log`。源代码包刻意不包含运行证据；`sparse-downloader-submission.zip` 另外包含本次实际编译及本机复核日志。

## 真实板端已执行的检查

已通过 SSH 登录 `cat@192.168.137.19`，公钥与此前保存的鲁班猫身份匹配，在新的独立项目目录执行 `bash scripts/board_verify.sh`。设备型号为 `EmbedFire LubanCat-1`，Ubuntu 20.04.6 LTS、Linux 4.19.232 / aarch64，数据目录位于 `/dev/mmcblk1p3` 的 ext4 文件系统；Python 3.8.10、GCC 9.4.0。

| 检查 | 实际结果 |
|---|---|
| 板端原生严格告警构建 | 成功，未将交叉编译代替板端构建 |
| 集成测试 | `Ran 16 tests in 2.438s`、`OK`；16 通过，0 失败、0 错误、0 跳过 |
| 创建 1 MiB 空洞文件 | 逻辑 1048576 字节；分配块 0，实际占用 0 字节 |
| 偏移 65536 定点写入 12 字节 | 逻辑长度不变；分配 8 个 512 字节单位，即 4096 字节，空间占比 0.391% |
| 真实 SIGINT | 保存偏移 4096，`result=interrupted`，退出 130 |
| 重启恢复 | `resume_from=4096`，最终偏移 1048576 |
| 完整校验 | `verified_bytes=1048576`、`result=verified`；最终进度 100% |
| 验证脚本 | `BOARD_VERIFY_RESULT=PASS` |

原始输出：`evidence/board-20261016-native-verification.log`；结构化摘要：`evidence/board-20261016-results.json`；教师阅读版见 `docs/board-test-report.md`。日志中的 `2026-10-15T17:18:58Z` 对应北京时间 `2026-10-16 01:18:58`，日期没有矛盾。板端源码 SHA-256 与本机已记录的 `cfb0c80b73b0dff620ff79a9c3d91881088acdbacf25d973e96699e44c6fdb21` 一致。

## 最终交付验证

源码、运行结果、AI 协作及审查材料和四组原生终端截图已经齐备。截图从开发板 X11 终端窗口通过 `xwd` 采集像素，`ffmpeg` 仅转换为 PNG；未绘制、拼接或改写终端内容，采集元数据为 `evidence/board-20261016-screenshots.json`。截图 01 的再次测试为 16 项通过、耗时 2.404 秒；主日志的 2.438 秒来自另一次实际运行，不能混作同一次耗时。

交付源码已解压到新的板端目录并原生重建，128 KiB 创建、续传和完整验证全部成功。记录见 `evidence/board-20261016-release-check.json`；最终包内所有核心源码、脚本、Makefile 与这次重建的文件逐字节哈希一致。归档附 `MANIFEST.json` 与外部 SHA-256 校验值，完整证据包为 `dist/sparse-downloader-submission.zip`。课堂分享仍需本人按课程安排进行。


## 已完成的连接与环境核对

Windows 的 WLAN → 以太网共享已修复，电脑网口为 `192.168.137.1`。此前发现的 `192.168.137.19` 和 `192.168.137.30` 均有 SSH 响应且主机公钥匹配同一既存身份；本次实际登录和板端测试使用 `.19`。

## 复现方式

把项目复制到开发板，进入项目根目录执行：

```sh
bash scripts/board_verify.sh
```

本次脚本已正常结束并输出 `BOARD_VERIFY_RESULT=PASS`，四组截图也已取得。之后复现应保留新运行的完整日志及跳过原因，不复用旧结果冒充新执行。

本次 GPT/Codex 记录已整理，DeepSeek 不再列为当前待办。如另外需要 DeepSeek 对照，可在自己的终端安全配置 `DEEPSEEK_API_KEY` 后，显式运行 `scripts/deepseek_workflow.py --call-api` 并选择阶段；默认执行脚本只准备提示词，不会联网或产生 API 费用。真实输出需要另行审核和记录采纳判断。
