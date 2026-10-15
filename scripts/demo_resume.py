#!/usr/bin/env python3
"""Run a real SIGINT/resume demonstration on Linux; print actual process output."""
from __future__ import annotations

import argparse
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def main() -> None:
    if sys.platform != "linux":
        raise SystemExit("This demonstration requires a real Linux process and signal handling.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary", type=Path)
    parser.add_argument("evidence_dir", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    evidence = args.evidence_dir.resolve(strict=True)
    directory = Path(tempfile.mkdtemp(prefix="resume-demo-", dir=evidence))
    target = directory / "download.bin"
    state = Path(str(target) + ".state")

    def run(*arguments: str) -> subprocess.CompletedProcess:
        command = [str(binary), *map(str, arguments)]
        print("$ " + " ".join(command), flush=True)
        result = subprocess.run(command, text=True, capture_output=True, timeout=60)
        print(result.stdout, end="", flush=True)
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr, flush=True)
        print("exit_code=" + str(result.returncode), flush=True)
        if result.returncode != 0:
            raise RuntimeError("Demonstration command failed")
        return result

    run("create", target, "1048576")
    command = [str(binary), "resume", str(target), "4096", "100"]
    print("$ " + " ".join(command), flush=True)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Resume process exited before interruption")
            try:
                fields = state.read_text(encoding="ascii").split()
                if len(fields) == 5 and fields[0] == "SPARSE_DL_V1" and int(fields[4]) > 0:
                    break
            except FileNotFoundError:
                pass
            time.sleep(0.01)
        else:
            raise RuntimeError("Timed out waiting for a committed nonzero checkpoint")
        print("Sending SIGINT after observing an actual committed checkpoint", flush=True)
        process.send_signal(signal.SIGINT)
        output, errors = process.communicate(timeout=20)
        print(output, end="", flush=True)
        if errors:
            print(errors, end="", file=sys.stderr, flush=True)
        print("exit_code=" + str(process.returncode), flush=True)
        if process.returncode != 130 or "result=interrupted" not in output:
            raise RuntimeError("SIGINT did not produce the required interrupted result")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()
    fields = state.read_text(encoding="ascii").split()
    if len(fields) != 5 or fields[0] != "SPARSE_DL_V1":
        raise RuntimeError("Invalid committed checkpoint")
    done = int(fields[4])
    if not 0 < done < target.stat().st_size:
        raise RuntimeError("Checkpoint is not a partial completed prefix")
    print("Actual saved checkpoint: " + state.read_text(encoding="ascii").strip(), flush=True)
    run("status", target)
    resumed = run("resume", target, "65536", "0")
    if f"resume_from={done}" not in resumed.stdout.splitlines():
        raise RuntimeError("Restart did not resume at the saved offset")
    run("verify", target)
    run("status", target)
    print("RESUME_DEMO_RESULT=PASS", flush=True)
    print("Demonstration artifacts retained at " + str(directory), flush=True)


if __name__ == "__main__":
    main()
