请为 Linux/aarch64 鲁班猫 1 编写 C11 空洞文件断点续传教学程序和 Makefile。必须有 create/write/resume/status，逻辑大小至少 128KiB，使用 lseek+write；模拟数据为位置 n 的字节 1+n%251。使用独立进度文件，Ctrl+C 后可以恢复。解释错误处理和测试方法。输出初稿仅作为待审核建议。
