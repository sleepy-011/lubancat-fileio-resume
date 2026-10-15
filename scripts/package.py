#!/usr/bin/env python3
"""Create source-only submission archives with an internal SHA-256 manifest."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "sparse-downloader"
ROOT_FILES = {"README.md", "Makefile", ".gitignore", ".gitattributes", "LICENSE"}
# Deliberate allowlist: never sweep the project, .env, tools, or board credentials.
ALLOWED = {
    "src": {".c", ".h"},
    "tests": {".py", ".sh", ".c"},
    "scripts": {".py", ".sh", ".ps1"},
    "docs": {".md", ".txt", ".json"},
    "ai-evidence": {".md", ".txt", ".json"},
    "review": {".c", ".patch", ".md", ".json", ".txt"},
}


def files() -> dict[str, bytes]:
    result = {}
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT)
        if path.is_symlink() or not path.is_file():
            continue
        if any(part.startswith(".") or part == "__pycache__"
               for part in relative.parts[:-1]):
            continue
        if len(relative.parts) == 1:
            allowed = relative.name in ROOT_FILES
        else:
            allowed = path.suffix.lower() in ALLOWED.get(relative.parts[0], set())
        if allowed and (not path.name.startswith(".") or relative.name in ROOT_FILES) and ".tmp" not in path.name:
            result[relative.as_posix()] = path.read_bytes()
    if not result or "src/sparse_dl.c" not in result or "Makefile" not in result:
        raise SystemExit("Required source/Makefile is missing; refusing incomplete archive")
    return result


def main() -> None:
    payload = files()
    manifest = {
        "format": 1,
        "description": "Source-only submission; hashes cover every other archive member.",
        "files": [{"path": name, "size": len(data),
                   "sha256": hashlib.sha256(data).hexdigest()}
                  for name, data in payload.items()],
    }
    payload["MANIFEST.json"] = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    zip_path = dist / f"{PREFIX}-source.zip"
    tar_path = dist / f"{PREFIX}-source.tar.gz"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            item = zipfile.ZipInfo(f"{PREFIX}/{name}", (2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = (0o100755 if name.endswith(".sh") else 0o100644) << 16
            archive.writestr(item, data)
    with tarfile.open(tar_path, "w:gz") as archive:
        for name, data in payload.items():
            item = tarfile.TarInfo(f"{PREFIX}/{name}")
            item.size = len(data)
            item.mode = 0o755 if name.endswith(".sh") else 0o644
            item.mtime = 0
            archive.addfile(item, io.BytesIO(data))
    hashes = []
    for path in (zip_path, tar_path):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes.append(f"{digest}  {path.name}")
        print(f"Created {path.name}: {path.stat().st_size} bytes")
    (dist / "SHA256SUMS.txt").write_text("\n".join(hashes) + "\n", encoding="ascii")
    print(f"Packaged {len(payload) - 1} allowlisted files plus MANIFEST.json")


if __name__ == "__main__":
    main()
