#!/usr/bin/env python3
"""
将本地 linux.do 阅读生成的 storage state 导出为 GitHub secret 格式（STORAGE_STAGES_JSON）。

用法:
    uv run python scripts/export_storage_secret.py
    # 输出即 STORAGE_STAGES_JSON secret 的 Value

    uv run python scripts/export_storage_secret.py --output secret_payload.json
    # 或写入文件（secret_payload.json 已在 .gitignore 中）

说明:
    workflow 里注入 storage state 时按 key 拼文件名：
        storage-states/linuxdo_$($prop.Name)_storage_state.json
    key 必须是脚本里算的用户名 hash: sha256(username)[:8]
    本工具直接从本地生成的文件名中提取 hash，避免手动拼错。
"""

import argparse
import json
import sys
from pathlib import Path

STORAGE_STATE_DIR = Path("storage-states")


def main() -> int:
    parser = argparse.ArgumentParser(description="导出 STORAGE_STAGES_JSON secret 内容")
    parser.add_argument("--output", "-o", help="输出到文件（默认输出到 stdout）")
    args = parser.parse_args()

    files = sorted(STORAGE_STATE_DIR.glob("linuxdo_*_storage_state.json"))
    if not files:
        print("❌ 未找到 storage state 文件，请先本地运行: uv run python linuxdo_read_posts.py", file=sys.stderr)
        return 1

    result = {}
    for f in files:
        # 文件名格式: linuxdo_{username_hash}_storage_state.json
        name = f.stem  # linuxdo_{hash}_storage_state
        username_hash = name.split("_")[1]
        data = json.loads(f.read_text(encoding="utf-8"))
        result[username_hash] = data
        print(f"✅ 已打包: {f.name} (key={username_hash})", file=sys.stderr)

    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
        print(f"✅ 已写入 {args.output}，将内容复制到 GitHub secret STORAGE_STAGES_JSON", file=sys.stderr)
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
