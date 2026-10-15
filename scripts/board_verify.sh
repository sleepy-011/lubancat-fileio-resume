#!/usr/bin/env bash
# Run on the actual Linux board. Preserve real output and return the test status.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
mkdir -p evidence
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
log="evidence/board-${timestamp}-$$.log"
set +e
(
    set -e
    printf 'Capture kind: actual command output, not a native terminal screenshot\n'
    printf 'UTC time: '; date -u '+%Y-%m-%dT%H:%M:%SZ'
    printf '\n== Kernel / architecture ==\n'; uname -a
    printf '\n== Operating system ==\n'; cat /etc/os-release
    printf '\n== Filesystem ==\n'; df -T .
    printf '\n== Compiler ==\n'; cc --version
    printf '\n== Build and regression tests ==\n'
    make clean
    make check
    printf '\n== File IO demonstration ==\n'
    demo=$(mktemp -d "$PWD/evidence/demo-${timestamp}.XXXXXX")
    ./sparse-dl create "$demo/sample.bin" 1048576
    ./sparse-dl status "$demo/sample.bin"
    ./sparse-dl write "$demo/sample.bin" 65536 FILE_IO_DEMO
    ./sparse-dl status "$demo/sample.bin"
    printf '\n== Actual SIGINT and resume demonstration ==\n'
    python3 scripts/demo_resume.py ./sparse-dl "$PWD/evidence"
    printf '\n== Source checksums ==\n'
    sha256sum src/sparse_dl.c Makefile tests/test_cli.py
    printf '\nBOARD_VERIFY_RESULT=PASS\n'
) 2>&1 | tee "$log"
pipeline_status=("${PIPESTATUS[@]}")
set -e
if (( pipeline_status[0] != 0 || pipeline_status[1] != 0 )); then
    printf '\nBOARD_VERIFY_RESULT=FAIL (command=%s, log-writer=%s)\n' "${pipeline_status[0]}" "${pipeline_status[1]}" | tee -a "$log"
    exit 1
fi
printf 'Evidence saved to %s\n' "$log"
