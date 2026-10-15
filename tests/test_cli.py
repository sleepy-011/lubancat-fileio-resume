#!/usr/bin/env python3
"""Linux integration tests; use a temporary directory and only Python's stdlib."""
import sys

if sys.platform != "linux":
    raise SystemExit("These integration tests require Linux (fcntl, signals, sparse files).")

import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(sys.argv.pop(1) if len(sys.argv) > 1 else ROOT / "sparse-dl").resolve()
SIZE = 131072


def expected(size):
    return bytes(1 + i % 251 for i in range(size))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sparse-dl-test-")
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.target = self.dir / "target.bin"

    def run_cli(self, *args, ok=True, env=None, timeout=10):
        p = subprocess.run([str(BINARY), *map(str, args)], capture_output=True,
                           text=True, timeout=timeout, env=env)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p

    def create(self, size=SIZE):
        self.run_cli("create", self.target, size)

    def status(self):
        return dict(line.split("=", 1) for line in
                    self.run_cli("status", self.target).stdout.splitlines())

    def state_bytes(self, done, suffix=b"\n"):
        st = self.target.stat()
        return (f"SPARSE_DL_V1 {st.st_dev} {st.st_ino} {st.st_size} {done}".encode()
                + suffix)

    def state_path(self):
        return Path(str(self.target) + ".state")

    def assert_contents(self, size=SIZE):
        self.assertEqual(self.target.read_bytes(), expected(size))
        self.assertIn("result=verified", self.run_cli("verify", self.target).stdout)

    def test_create_is_sparse_and_status_matches_stat(self):
        self.create()
        st = self.target.stat()
        self.assertEqual(st.st_size, SIZE)
        self.assertEqual(self.target.read_bytes(), bytes(SIZE))
        self.assertLess(st.st_blocks * 512, SIZE, "test filesystem must support sparse files")
        status = self.status()
        self.assertEqual(int(status["logical_bytes"]), SIZE)
        self.assertEqual(int(status["allocated_blocks_512"]), st.st_blocks)
        self.assertEqual(int(status["allocated_bytes"]), st.st_blocks * 512)
        self.assertAlmostEqual(float(status["space_percent"]), st.st_blocks * 51200 / SIZE, places=3)
        self.assertEqual(status["completed_offset"], "0")
        self.assertEqual(status["state_exists"], "0")

    def test_create_refuses_small_existing_or_orphan_state(self):
        self.run_cli("create", self.target, SIZE - 1, ok=False)
        self.assertFalse(self.target.exists())
        self.target.write_bytes(b"keep me")
        self.run_cli("create", self.target, SIZE, ok=False)
        self.assertEqual(self.target.read_bytes(), b"keep me")
        self.target.unlink()
        self.state_path().write_bytes(b"orphan")
        self.run_cli("create", self.target, SIZE, ok=False)
        self.assertFalse(self.target.exists())

    def test_positioned_write_leaves_all_other_bytes_zero(self):
        self.create()
        self.run_cli("write", self.target, 65537, "HELLO")
        data = bytearray(SIZE)
        data[65537:65542] = b"HELLO"
        self.assertEqual(self.target.read_bytes(), data)
        self.assertLess(self.target.stat().st_blocks * 512, SIZE,
                        "positioned write must preserve unwritten sparse regions")
        self.run_cli("write", self.target, SIZE - 1, "Z")
        self.assertEqual(self.target.read_bytes()[-1:], b"Z")
        self.run_cli("write", self.target, SIZE, "")

    def test_invalid_arguments_and_ranges_do_not_mutate_target(self):
        self.create()
        cases = [("write", self.target, "-1", "X"),
                 ("write", self.target, SIZE, "X"),
                 ("write", self.target, SIZE + 1, ""),
                 ("resume", self.target, 0), ("resume", self.target, 65537),
                 ("resume", self.target, 4096, 60001),
                 ("create", self.dir / "bad", "18446744073709551616"),
                 ("status", self.dir / "missing"), ("unknown",)]
        for args in cases:
            with self.subTest(args=args):
                self.run_cli(*args, ok=False)
        self.assertEqual(self.target.read_bytes(), bytes(SIZE))

    def test_resume_and_verify_non_chunk_multiple(self):
        size = SIZE + 17
        self.create(size)
        self.run_cli("resume", self.target, 7777)
        self.assert_contents(size)
        status = self.status()
        self.assertEqual(int(status["completed_offset"]), size)
        self.assertEqual(float(status["progress_percent"]), 100.0)
        self.assertIn(f"resume_from={size}", self.run_cli("resume", self.target).stdout)
        self.run_cli("write", self.target, 0, "X", ok=False)

    def test_sigint_checkpoints_and_resumes_in_real_process(self):
        self.create()
        log = open(self.dir / "signal.log", "w+")
        self.addCleanup(log.close)
        p = subprocess.Popen([str(BINARY), "resume", str(self.target), "4096", "200"],
                             stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if p.poll() is not None:
                    self.fail("resume exited before SIGINT")
                try:
                    done = int(self.state_path().read_text().split()[-1])
                    if 0 < done < SIZE:
                        break
                except (FileNotFoundError, ValueError, IndexError):
                    pass
                time.sleep(0.01)
            else:
                self.fail("checkpoint was not published within five seconds")
            p.send_signal(signal.SIGINT)
            self.assertEqual(p.wait(timeout=5), 130)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
        done = int(self.status()["completed_offset"])
        self.assertGreater(done, 0)
        self.assertLess(done, SIZE)
        data = self.target.read_bytes()
        self.assertEqual(data[:done], expected(done))
        self.assertEqual(data[done:], bytes(SIZE - done))
        resumed = self.run_cli("resume", self.target, 8192)
        self.assertIn(f"resume_from={done}", resumed.stdout)
        self.assert_contents()

    def test_corrupted_and_noncanonical_states_are_rejected(self):
        self.create()
        valid = self.state_bytes(0)
        fields = valid.decode().strip().split(" ")
        variants = [b"", b"garbage\n", valid[:-1], valid + b"junk",
                    valid + b"\0", self.state_bytes(SIZE + 1),
                    self.state_bytes(-1), self.state_bytes("18446744073709551616")]
        for i in range(1, 5):
            changed = list(fields)
            # scanf's unsigned conversion may accept a minus sign even for zero.
            changed[i] = "-0" if i == 4 else "+" + changed[i]
            variants.append((" ".join(changed) + "\n").encode())
        for record in variants:
            with self.subTest(record=record):
                self.state_path().write_bytes(record)
                self.run_cli("status", self.target, ok=False)
                self.run_cli("resume", self.target, ok=False)
                self.assertEqual(self.target.read_bytes(), bytes(SIZE))

    def test_state_from_replaced_target_is_rejected(self):
        self.create()
        self.run_cli("resume", self.target, 65536)
        self.target.rename(self.dir / "original.bin")
        with self.target.open("wb") as f:
            f.truncate(SIZE)
        self.run_cli("resume", self.target, ok=False)
        self.run_cli("status", self.target, ok=False)

    def test_existing_lock_blocks_read_and_write_commands(self):
        self.create()
        with self.target.open("rb") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            for args in [("status",), ("verify",), ("resume",), ("write", 0, "X")]:
                self.run_cli(args[0], self.target, *args[1:], ok=False, timeout=2)
        self.run_cli("status", self.target)

    def test_fifo_and_symlink_are_rejected_without_hanging(self):
        os.mkfifo(self.target)
        for command in ("status", "verify", "resume"):
            self.run_cli(command, self.target, ok=False, timeout=2)
        self.target.unlink()
        other = self.dir / "real.bin"
        other.write_bytes(b"preserve")
        self.target.symlink_to(other)
        self.run_cli("status", self.target, ok=False)
        self.run_cli("write", self.target, 0, "X", ok=False)
        self.assertEqual(other.read_bytes(), b"preserve")

    def test_hardlink_alias_cannot_modify_managed_data(self):
        self.create()
        self.run_cli("resume", self.target, 65536)
        alias = self.dir / "alias.bin"
        os.link(self.target, alias)
        self.run_cli("write", alias, 0, "X", ok=False)
        self.run_cli("resume", alias, ok=False)
        self.assert_contents()

    def test_verify_detects_actual_content_corruption(self):
        self.create()
        self.run_cli("verify", self.target, ok=False)
        self.run_cli("resume", self.target, 65536)
        with self.target.open("r+b") as f:
            f.seek(54321)
            f.write(b"\0")
        p = self.run_cli("verify", self.target, ok=False)
        self.assertIn("54321", p.stderr)

    def test_resume_rejects_corrupted_prefix_or_forged_progress(self):
        self.create()
        self.state_path().write_bytes(self.state_bytes(SIZE))
        self.run_cli("resume", self.target, ok=False)
        self.state_path().unlink()
        self.run_cli("resume", self.target, 65536)
        with self.target.open("r+b") as f:
            f.seek(1024)
            f.write(b"\0")
        self.run_cli("resume", self.target, ok=False)

    def fault_env(self, mode):
        if os.environ.get("SPARSE_SKIP_FAULT_TESTS") == "1":
            self.skipTest("LD_PRELOAD fault injection explicitly disabled for sanitizer run")
        cc = shutil.which(os.environ.get("CC", "cc"))
        if not cc:
            self.skipTest("C compiler unavailable; LD_PRELOAD fault injection not executed")
        shim = self.dir / "fault_io.so"
        built = subprocess.run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                                "-shared", "-fPIC", str(ROOT / "tests" / "fault_io.c"),
                                "-ldl", "-o", str(shim)], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        env = dict(os.environ, LD_PRELOAD=str(shim), FAULT_TARGET=str(self.target),
                   FAULT_MODE=mode, FAULT_LOG=str(self.dir / "fault.log"))
        return env

    def test_short_write_and_eintr_are_retried(self):
        self.create()
        env = self.fault_env("retry")
        self.run_cli("resume", self.target, 4096, env=env)
        events = (self.dir / "fault.log").read_text()
        self.assertIn("E", events, "EINTR injection must actually occur")
        self.assertIn("S", events, "short write injection must actually occur")
        self.assert_contents()

    def test_write_failure_preserves_checkpoint_and_can_restart(self):
        self.create()
        env = self.fault_env("fail")
        self.run_cli("resume", self.target, 4096, env=env, ok=False)
        self.assertEqual(int(self.status()["completed_offset"]), 0)
        self.assertIn("F", (self.dir / "fault.log").read_text())
        self.run_cli("resume", self.target, 65536)
        self.assert_contents()

    def test_zero_write_fails_without_infinite_loop(self):
        self.create()
        env = self.fault_env("zero")
        self.run_cli("resume", self.target, 4096, env=env, ok=False, timeout=2)
        self.assertEqual(int(self.status()["completed_offset"]), 0)
        self.assertIn("Z", (self.dir / "fault.log").read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
