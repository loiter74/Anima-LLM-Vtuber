"""生成 RVC 晋级候选；不会直接覆盖 Animetta 正式配置。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.train.workspace import load_project


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_candidate(
    project_root: Path,
    *,
    run_id: str,
    model_path: Path,
    index_path: Path,
    voice: str,
) -> dict[str, Any]:
    project = load_project(project_root)
    runtime = _table(project, "runtime")
    inference = _table(project, "inference")
    rvc_root = Path(str(runtime["rvc_root"])).resolve()
    model = model_path.resolve()
    index = index_path.resolve()
    if not model.is_file() or model.suffix.lower() != ".pth":
        raise ValueError(f"模型不存在或不是 .pth：{model}")
    if not index.is_file() or index.suffix.lower() != ".index":
        raise ValueError(f"索引不存在或不是 .index：{index}")
    try:
        model.relative_to(rvc_root)
        relative_index = index.relative_to(rvc_root).as_posix()
    except ValueError as error:
        raise ValueError("候选模型和 index 必须位于配置的 RVC 根目录内") from error
    if not run_id.strip() or not voice.strip():
        raise ValueError("run_id 和 voice 不能为空")
    model_sha256 = sha256_file(model)
    index_sha256 = sha256_file(index)
    revision_payload = {
        "project_id": project["project_id"],
        "run_id": run_id.strip(),
        "model_sha256": model_sha256,
        "index_sha256": index_sha256,
        "inference": dict(inference),
    }
    revision = hashlib.sha256(
        json.dumps(revision_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    identity = {
        "provider": "rvc-webui-host",
        "model": model.name,
        "revision": revision,
        "voice": voice.strip(),
        "sample_rate": int(project["data"]["sample_rate"]),
    }
    return {
        "schema_version": 1,
        "status": "candidate",
        "project_id": project["project_id"],
        "run_id": run_id.strip(),
        "identity": identity,
        "host_rvc_patch": {
            "identity": identity,
            "runtime": {
                "model_sha256": model_sha256.upper(),
                "index_path": relative_index,
                "index_sha256": index_sha256.upper(),
            },
        },
        "singing_patch": {
            "model_name": model.name,
            "index_path": relative_index,
            "expected_revision": revision,
            "f0_method": "rmvpe",
            **dict(inference),
        },
        "required_actions": [
            "人工确认固定评测与 AB 门禁通过",
            "同步合并 host-rvc.yaml 与 singing.yaml 的候选字段",
            "通过 runtime_lifecycle.py host-rvc-restart 重启宿主服务",
            "运行 RVC 模型预检并在 /live.html 验证真实转换与播放证据",
        ],
    }


def _table(values: Mapping[str, Any], field: str) -> Mapping[str, Any]:
    value = values.get(field)
    if not isinstance(value, dict):
        raise ValueError(f"project.toml 缺少 [{field}] 表")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="生成不落生产的 RVC 晋级候选")
    parser.add_argument("--project", type=Path, default=Path("songs"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.output.exists() and not args.force:
        print(f"[ERROR] 晋级候选已存在：{args.output}", file=sys.stderr)
        return 1
    try:
        candidate = build_candidate(
            args.project.resolve(),
            run_id=args.run_id,
            model_path=args.model,
            index_path=args.index,
            voice=args.voice,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (KeyError, OSError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1
    print(f"晋级候选已生成，正式配置未修改：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
