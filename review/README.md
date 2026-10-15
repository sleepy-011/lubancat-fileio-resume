# 初版与修复记录

`v1/sparse_dl.c` 是本次 Codex 实际生成、随后被审查的第一版代码，只用于审查对比，不是最终提交的构建入口。

- 初版 SHA-256：`e646c5c6a75489399fd282711d31d768a0f5e026075edcba56aaa3caa6dee21f`
- 最终构建入口：`src/sparse_dl.c`
- 实际修复说明：`docs/code-review.md`
- 对应修改：`fixes.patch`

Linux 下可用同一套黑盒回归测试比较前后行为：

```sh
cc -std=c11 -O2 -Wall -Wextra -Wpedantic review/v1/sparse_dl.c -o /tmp/sparse-dl-v1
python3 tests/test_cli.py /tmp/sparse-dl-v1
make check
```

初版出现回归失败属于预期，但只有真实执行并保存输出后，才能在报告中填写失败项目和最终通过数量。
