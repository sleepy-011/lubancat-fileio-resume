#!/usr/bin/env python3
"""Preserve an existing board log; deliberately does not fabricate a screenshot."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Existing real board output log")
    args = parser.parse_args()
    source = args.log.resolve(strict=True)
    if not source.is_file():
        parser.error("log must be a regular file")
    data = source.read_bytes()
    if not data:
        parser.error("log is empty")
    report = {"kind": "log-integrity-record", "source_filename": source.name,
              "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "note": "仅保留日志及校验值；不是原生终端截图。校验值不证明日志来源。"}
    destination = source.with_name(source.name + ".sha256.json")
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved integrity record: {destination}")
    print("No image was generated. Capture the actual board terminal for a native screenshot.")


if __name__ == "__main__":
    main()
