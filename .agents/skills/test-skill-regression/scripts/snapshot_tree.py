#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path

DEFAULT_EXCLUDES = frozenset({".git", ".skill-regression", "__pycache__"})


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, output: Path, excludes: set[str]) -> dict[str, object]:
    resolved_root = root.resolve(strict=True)
    resolved_output = output.resolve()
    files: dict[str, dict[str, int | str]] = {}

    for path in sorted(resolved_root.rglob("*")):
        if not path.is_file() or path.resolve() == resolved_output:
            continue
        relative = path.relative_to(resolved_root)
        if any(part in excludes for part in relative.parts):
            continue
        files[relative.as_posix()] = {
            "sha256": sha256_file(path),
            "size": path.stat().st_size,
        }

    return {"schema_version": 1, "files": files}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="为目录创建确定性的文件清单。")
    parser.add_argument("root", type=Path, help="要快照的目录")
    parser.add_argument("output", type=Path, help="输出 JSON 清单")
    parser.add_argument("--exclude", action="append", default=[], help="额外排除的目录名")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    excludes = set(DEFAULT_EXCLUDES) | set(args.exclude)
    payload = build_manifest(args.root, args.output, excludes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{len(payload['files'])} 个文件 -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
