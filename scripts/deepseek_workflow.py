#!/usr/bin/env python3
"""Prepare prompts; optionally capture real DeepSeek API responses without edits."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = [
    ("01-initial", "请为 Linux/aarch64 鲁班猫 1 编写 C11 空洞文件断点续传教学程序和 Makefile。必须有 create/write/resume/status，逻辑大小至少 128KiB，使用 lseek+write；模拟数据为位置 n 的字节 1+n%251。使用独立进度文件，Ctrl+C 后可以恢复。解释错误处理和测试方法。输出初稿仅作为待审核建议。"),
    ("02-review", "请审查附件当前 C 程序的正确性，重点检查部分写入、信号处理、状态保存顺序、路径/符号链接/硬链接、数值溢出、越界与数据完整性。只报告可以依据代码解释的真实缺陷，使用现象、根因、复现/验证三个字段；不要凑数量。"),
    ("03-tests", "请针对附件程序提出可执行的 CLI 黑盒测试，包括空洞占用、定点写入、Ctrl+C 和 SIGKILL 恢复、损坏状态、越界、锁冲突、符号链接、最终内容校验。将预期与实际区分，不要声称已经运行测试。"),
    ("04-optimize", "请提出可审核的小范围优化建议，保留 Linux lseek/write 教学重点，优先正确性和清晰性。解释每项改动的收益、代价和需要验证的行为，不要直接声称优化已被采纳。"),
    ("05-readme", "请逐节核对下面 README 与当前源码是否一致，指出命令参数、模拟下载范围、文件占用单位、恢复机制、测试与 AI 证据表述中的错误。真实测试和未执行测试要明确区分。只提出修改建议。"),
]


def prepare() -> list[tuple[str, str]]:
    destination = ROOT / "ai-evidence" / "prompts"
    destination.mkdir(parents=True, exist_ok=True)
    output = []
    for name, prompt in PROMPTS:
        context = ""
        # Initial generation must not be seeded with the reviewed final solution.
        if name != "01-initial":
            context += "\n\n当前源码：\n```c\n" + (ROOT / "src/sparse_dl.c").read_text(encoding="utf-8") + "\n```\n"
        if name == "05-readme" and (ROOT / "README.md").exists():
            context += "\nREADME：\n" + (ROOT / "README.md").read_text(encoding="utf-8")
        full = prompt + context
        (destination / f"{name}.md").write_bytes((full + "\n").encode("utf-8"))
        output.append((name, full))
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call-api", action="store_true", help="Explicitly enable billable API requests")
    parser.add_argument("--stage", choices=[item[0] for item in PROMPTS] + ["all"], default="01-initial")
    # Official model documentation (verified 2026-10-15): https://api-docs.deepseek.com/
    parser.add_argument("--model", default="deepseek-flash")
    args = parser.parse_args()
    prompts = prepare()
    print("Prepared five prompts in ai-evidence/prompts. Preparation is not API evidence.")
    if not args.call_api:
        print("No network requests made. Use --call-api to explicitly enable API requests.")
        return
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise SystemExit("DEEPSEEK_API_KEY is required; no API request was made.")
    output = ROOT / "ai-evidence" / "responses"
    output.mkdir(parents=True, exist_ok=True)
    for name, prompt in prompts:
        if args.stage not in (name, "all"):
            continue
        data = json.dumps({"model": args.model, "messages": [{"role": "user", "content": prompt}],
                           "max_tokens": 8192, "stream": False}).encode("utf-8")
        request = urllib.request.Request("https://api.deepseek.com/chat/completions", data=data,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": "Bearer " + key}, method="POST")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            # Never log request headers, environment, or server bodies on errors.
            raise SystemExit(f"API returned HTTP {error.code}; no credentials were logged.") from None
        except (urllib.error.URLError, TimeoutError):
            raise SystemExit("API connection failed; credentials were not logged.") from None
        result = json.loads(raw)
        if "choices" not in result:
            raise SystemExit("API response lacked choices; no source files changed.")
        stem = output / f"{timestamp}-{name}"
        Path(str(stem) + ".json").write_bytes(raw)
        # Preserve the exact request body separately: prompt files may later be refreshed.
        # API credentials occur only in the HTTP header and are absent from this body.
        Path(str(stem) + ".request.json").write_bytes(data)
        metadata = {"captured_at_utc": timestamp, "provider": "DeepSeek",
                    "endpoint": "https://api.deepseek.com/chat/completions", "http_status": status,
                    "requested_model": args.model, "stage": name,
                    "request_body_sha256": hashlib.sha256(data).hexdigest(),
                    "response_body_sha256": hashlib.sha256(raw).hexdigest(),
                    "note": "Real raw API response; unreviewed; never automatically installed as source."}
        Path(str(stem) + ".meta.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        print(f"Saved real raw API response for {name}; reviewed source was not changed.")


if __name__ == "__main__":
    main()
