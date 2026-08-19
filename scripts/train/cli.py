"""Fail-fast RVC baseline runner for the tracked ``songs`` workspace."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.train.workspace import TrainingStep, build_rvc_plan, validate_workspace


def run_step(
    step_name: str,
    command: Sequence[str],
    *,
    cwd: str | Path,
    success_exit_codes: Sequence[int] = (0,),
) -> None:
    """Run one step and stop the pipeline immediately on a non-zero exit."""
    started = time.monotonic()
    print(f"[{step_name}] cwd={cwd}")
    print(subprocess.list2cmdline(list(command)))
    result = subprocess.run(list(command), cwd=cwd, check=False)  # noqa: S603 - reviewed RVC argv
    if result.returncode not in success_exit_codes:
        print(f"[{step_name}] 失败，已停止后续步骤。", file=sys.stderr)
        raise subprocess.CalledProcessError(result.returncode, list(command))
    print(f"[{step_name}] 完成，用时 {time.monotonic() - started:.1f}s")


def _validate_gpu_evidence(path: Path, *, run_id: str, batch_size: int) -> None:
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取 GPU 峰值探针证据：{path}") from error
    if evidence.get("schema_version") != 1 or evidence.get("run_id") != run_id:
        raise ValueError("GPU 证据版本或 run_id 不匹配")
    if evidence.get("batch_size") != batch_size:
        raise ValueError("GPU 证据 batch_size 与本次训练不一致")
    total = evidence.get("memory_total_mib")
    peak = evidence.get("memory_peak_used_mib")
    if not isinstance(total, int) or not isinstance(peak, int) or peak <= 0 or total <= peak:
        raise ValueError("GPU 证据缺少有效的总显存或峰值显存")
    required_free = max(round(total * 0.25), 6144)
    if total - peak < required_free:
        raise ValueError(f"GPU 峰值探针只剩 {total - peak} MiB，要求至少 {required_free} MiB")
    if evidence.get("competing_processes") != []:
        raise ValueError("GPU 证据仍包含同类竞争进程")
    if evidence.get("workspace_lifecycle_clear") is not True:
        raise ValueError("GPU 证据未确认同工作区生命周期任务已清空")
    if not str(evidence.get("gpu_name", "")).strip():
        raise ValueError("GPU 证据缺少显卡型号")
    probe_command = evidence.get("probe_command")
    if (
        not isinstance(probe_command, list)
        or not probe_command
        or not all(isinstance(part, str) and part.strip() for part in probe_command)
    ):
        raise ValueError("GPU 证据缺少有界峰值探针完整 argv")
    try:
        observed_at = datetime.fromisoformat(str(evidence["observed_at"]))
    except (KeyError, ValueError) as error:
        raise ValueError("GPU 证据 observed_at 必须是 ISO-8601 时间") from error
    if observed_at.tzinfo is None:
        raise ValueError("GPU 证据 observed_at 必须包含时区")
    age = datetime.now(UTC) - observed_at.astimezone(UTC)
    if age < timedelta(0) or age > timedelta(hours=4):
        raise ValueError("GPU 峰值探针证据必须在最近 4 小时内生成")


def _preflight(
    project: Path,
    run_id: str,
    evidence_path: Path,
    *,
    resume: bool,
) -> list[TrainingStep]:
    errors = validate_workspace(project, stage="dataset")
    if errors:
        raise ValueError("数据集未就绪：" + "; ".join(errors))
    plan = build_rvc_plan(project, run_id=run_id)
    train_step = next(step for step in plan if step.name == "train")
    batch_index = train_step.command.index("-bs") + 1
    _validate_gpu_evidence(
        evidence_path,
        run_id=run_id,
        batch_size=int(train_step.command[batch_index]),
    )
    dataset_dir = project / "audio" / "dataset" / "train"
    if not any(dataset_dir.glob("*.wav")):
        raise ValueError("训练目录为空；请先运行 materialize_dataset")
    experiment_dir = Path(train_step.cwd) / "logs" / run_id
    if resume:
        for required in (experiment_dir / "config.json", experiment_dir / "filelist.txt"):
            if not required.is_file():
                raise ValueError(f"无法恢复；缺少 RVC checkpoint 上下文：{required}")
    elif experiment_dir.exists() and any(experiment_dir.iterdir()):
        raise ValueError("同名 RVC experiment 已存在；使用新的 run-id 或显式 --resume")
    for flag in ("-pg", "-pd"):
        dependency = Path(train_step.command[train_step.command.index(flag) + 1])
        if not dependency.is_file():
            raise ValueError(f"RVC 预训练权重不存在：{dependency}")
    for step in plan:
        if not Path(step.command[0]).is_file():
            raise ValueError(f"RVC Python 不存在：{step.command[0]}")
        configured_entrypoint = Path(step.command[1])
        entrypoint = (
            configured_entrypoint
            if configured_entrypoint.is_absolute()
            else Path(step.cwd) / configured_entrypoint
        )
        if not entrypoint.is_file():
            raise ValueError(f"RVC 入口不存在：{entrypoint}")
    return plan


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="执行 RVC v2 + RMVPE baseline")
    parser.add_argument("--project", type=Path, default=Path("songs"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execute", action="store_true", help="实际执行；默认只输出计划")
    parser.add_argument("--gpu-probe-evidence", type=Path)
    parser.add_argument("--preprocess-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="从同 run-id 的 RVC checkpoint 恢复")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project = args.project.resolve()
    try:
        plan = build_rvc_plan(project, run_id=args.run_id)
        if not args.execute:
            print(
                json.dumps(
                    {"schema_version": 1, "steps": [step.as_dict() for step in plan]},
                    ensure_ascii=False,
                    indent=2,
                )
            )
            print("仅生成计划；未启动 GPU 任务。")
            return 0
        if args.gpu_probe_evidence is None:
            raise ValueError("实际训练必须提供 --gpu-probe-evidence")
        if args.preprocess_only and args.resume:
            raise ValueError("--preprocess-only 与 --resume 不能同时使用")
        plan = _preflight(
            project,
            args.run_id,
            args.gpu_probe_evidence,
            resume=args.resume,
        )
        train_index = next(index for index, step in enumerate(plan) if step.name == "train")
        if args.preprocess_only:
            selected = plan[:train_index]
        elif args.resume:
            selected = plan[train_index:]
        else:
            selected = plan
        for step in selected:
            run_step(
                step.name,
                step.command,
                cwd=step.cwd,
                success_exit_codes=step.success_exit_codes,
            )
            missing_outputs = [path for path in step.required_outputs if not Path(path).is_file()]
            if missing_outputs:
                raise RuntimeError(f"{step.name} 未生成必需产物：{missing_outputs[0]}")
        print("训练步骤完成；模型尚未晋级到正式宿主运行时。")
        return 0
    except (KeyError, OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
