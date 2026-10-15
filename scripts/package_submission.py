#!/usr/bin/env python3
"""Add selected verification evidence to the source submission; never demo data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

from package import files

ROOT = Path(__file__).resolve().parents[1]
LOGS = (
    "evidence/cross-build-20261015T052638Z.log",
    "evidence/local-verification.log",
)
BOARD_NAME = re.compile(r"board-[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:log|json|png)\Z")


def board_evidence(names):
    """Read explicit top-level board evidence files, never recurse into demo dirs.

    A PNG signature confirms file format only. Actual screenshot provenance must
    be established when capturing it; this script does not manufacture images.
    """
    result = {}
    directory = ROOT / "evidence"
    for name in names:
        if not BOARD_NAME.fullmatch(name):
            raise SystemExit("Board evidence must be a basename matching board-*.log/json/png: " + name)
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise SystemExit("Missing regular board evidence file: " + name)
        if path.resolve().parent != directory.resolve():
            raise SystemExit("Board evidence escaped the evidence directory: " + name)
        data = path.read_bytes()
        if not data:
            raise SystemExit("Empty board evidence file: " + name)
        if path.suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise SystemExit("Selected screenshot is not a PNG file: " + name)
        if path.suffix == ".json":
            try:
                json.loads(data.decode("utf-8-sig"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise SystemExit("Selected board evidence is not valid UTF-8 JSON: " + name) from None
        result["evidence/" + name] = data
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-evidence", nargs="+", default=[], metavar="BASENAME",
                        help="Explicit actual evidence basenames in evidence/; only board-*.log/json/png")
    args = parser.parse_args()
    payload = files()
    for name in LOGS:
        path = ROOT / name
        if not path.is_file():
            raise SystemExit("Missing actual evidence log: " + name)
        payload[name] = path.read_bytes()
    selected_board = board_evidence(args.board_evidence)
    payload.update(selected_board)
    entries = [{"path": name, "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest()}
               for name, data in sorted(payload.items())]
    manifest = {"format": 1,
                "description": "Reviewed source and explicitly selected verification evidence. Hashes establish integrity, not origin.",
                "board_evidence_status": "provided" if selected_board else "pending",
                "selected_board_evidence": sorted(selected_board), "files": entries}
    payload["MANIFEST.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode()
    destination = ROOT / "dist" / "sparse-downloader-submission.zip"
    destination.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            member = zipfile.ZipInfo("sparse-downloader/" + name, (2026, 1, 1, 0, 0, 0))
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(member, data)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(".zip.sha256").write_text(digest + "  " + destination.name + "\n", encoding="ascii")
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP integrity check failed")
        for entry in entries:
            data = archive.read("sparse-downloader/" + entry["path"])
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise SystemExit("Hash mismatch: " + entry["path"])
    print("Submission archive verified:", destination.name)
    print("Files including manifest:", len(payload))
    print("Explicit board evidence files:", len(selected_board))


if __name__ == "__main__":
    main()
