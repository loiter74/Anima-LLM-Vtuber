"""Unified capture, validate, replay, and report command line interface."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path
from typing import Any

from animetta.services.bilibili import ReplyCandidate

from .capture import AnonymousLivestreamCollector
from .dataset import DatasetValidator, DatasetWriter, HeatTier
from .pipeline import CleanOptions, publish_clean_datasets
from .reporting import load_safety_assessment, write_report
from .runner import EvaluationRunner, default_bursts
from .semantic import create_deepseek_semantic_processor
from .socket_processor import SocketIOFullStackProcessor
from .twitch_vod import TwitchVodCollector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="livestream-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="observe and anonymously capture a public room")
    capture.add_argument(
        "--platform",
        choices=("bilibili-live", "twitch-vod"),
        default="bilibili-live",
    )
    capture.add_argument("--room-id", type=int)
    capture.add_argument("--vod-id")
    capture.add_argument("--start-minutes", type=float, default=0)
    capture.add_argument("--rate-cap-per-minute", type=int)
    capture.add_argument("--deterministic-prefilter", action="store_true")
    capture.add_argument("--tier", required=True, choices=[tier.value for tier in HeatTier])
    capture.add_argument("--dataset-id", required=True)
    capture.add_argument("--duration-minutes", type=float, default=120)
    capture.add_argument("--observe-minutes", type=float, default=15)
    capture.add_argument("--output-root", type=Path, default=Path("data/livestream_eval"))

    validate = subparsers.add_parser("validate", help="validate a sanitized dataset")
    validate.add_argument("--dataset", required=True, type=Path)

    clean = subparsers.add_parser("clean", help="clean and enrich a sanitized source dataset")
    clean.add_argument("--dataset", required=True, type=Path)
    clean.add_argument("--output-root", type=Path, default=Path("data/livestream_eval"))
    clean.add_argument("--profile", default="balanced")
    clean.add_argument("--target-language", default="zh-CN")
    clean.add_argument("--synthetic-ratio", type=float, default=0.10)
    clean.add_argument("--seed", type=int, default=20260717)
    clean.add_argument("--llm-profile", default="production")
    clean.add_argument("--derive-medium", action="store_true")
    clean.add_argument("--medium-rate", type=int, default=40)
    clean.add_argument("--config", type=Path, default=Path("config/animetta.yaml"))

    replay = subparsers.add_parser("replay", help="run transport or injected full-stack replay")
    replay.add_argument("--dataset", required=True, type=Path)
    replay.add_argument("--mode", choices=("transport", "full"), default="transport")
    replay.add_argument("--speed", type=float)
    replay.add_argument("--burst-profile", choices=("none", "high"), default="none")
    replay.add_argument("--processor", help="full-mode async adapter as module:function")
    replay.add_argument("--server-url", default="http://localhost")
    replay.add_argument(
        "--duration-minutes",
        type=float,
        help="source timeline window; full mode defaults to 90 minutes",
    )
    replay.add_argument("--resource-pid", type=int)
    replay.add_argument("--resource-container", default="animetta")
    replay.add_argument("--safety-assessment", type=Path)
    replay.add_argument("--output", type=Path)

    report = subparsers.add_parser("report", help="generate JSON/Markdown/manual-score outputs")
    report.add_argument("--run-dir", required=True, type=Path)
    report.add_argument("--scores", type=Path)
    report.add_argument(
        "--safety-assessment",
        type=Path,
        help="post-run reviewed safety JSON; defaults to the run directory template",
    )
    report.add_argument("--seed", type=int, default=20260716)
    return parser


def capture_dataset(args: argparse.Namespace) -> Path:
    if args.duration_minutes < 120:
        raise ValueError("formal capture duration must be at least 120 minutes")
    if args.observe_minutes < 15:
        raise ValueError("candidate observation must be at least 15 minutes")
    heat_tier = HeatTier(args.tier)
    if args.platform == "twitch-vod":
        return _capture_twitch_vod_dataset(args, heat_tier)
    if args.rate_cap_per_minute is not None or args.deterministic_prefilter:
        raise ValueError("capture shaping options are only supported for twitch-vod capture")
    if args.room_id is None:
        raise ValueError("--room-id is required for bilibili-live capture")
    if args.observe_minutes:
        with tempfile.TemporaryDirectory(prefix="animetta-livestream-observe-") as temporary:
            observation_dir = Path(temporary)
            observation_writer = DatasetWriter(
                observation_dir,
                dataset_id="candidate-observation",
                heat_tier=heat_tier,
            )
            AnonymousLivestreamCollector(
                room_id=args.room_id,
                writer=observation_writer,
                duration_seconds=args.observe_minutes * 60,
            ).capture()
            observation = DatasetValidator().validate(observation_dir)
            if not observation.valid:
                raise ValueError(
                    "candidate room failed observation: " + ",".join(observation.error_codes),
                )
    dataset_dir = Path(args.output_root) / args.dataset_id
    if dataset_dir.exists() and any(dataset_dir.iterdir()):
        raise ValueError(f"dataset output already exists: {dataset_dir}")
    writer = DatasetWriter(dataset_dir, dataset_id=args.dataset_id, heat_tier=heat_tier)
    AnonymousLivestreamCollector(
        room_id=args.room_id,
        writer=writer,
        duration_seconds=args.duration_minutes * 60,
    ).capture()
    print(dataset_dir)
    return dataset_dir


def _capture_twitch_vod_dataset(args: argparse.Namespace, heat_tier: HeatTier) -> Path:
    if not args.vod_id:
        raise ValueError("--vod-id is required for twitch-vod capture")
    if args.start_minutes < 0:
        raise ValueError("--start-minutes must not be negative")
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    dataset_dir = output_root / args.dataset_id
    if dataset_dir.exists():
        raise ValueError(f"dataset output already exists: {dataset_dir}")
    with tempfile.TemporaryDirectory(
        prefix=f".{args.dataset_id}-",
        dir=output_root,
    ) as temporary:
        staging = Path(temporary) / "dataset"
        writer = DatasetWriter(
            staging,
            dataset_id=args.dataset_id,
            heat_tier=heat_tier,
            collector_version="twitch-vod-1",
        )
        try:
            TwitchVodCollector(
                vod_id=args.vod_id,
                writer=writer,
                start_seconds=round(args.start_minutes * 60),
                duration_seconds=round(args.duration_minutes * 60),
                rate_cap_per_minute=args.rate_cap_per_minute,
                deterministic_prefilter=args.deterministic_prefilter,
            ).capture()
        except BaseException:
            writer.abort()
            raise
        validation = DatasetValidator().validate(staging)
        if not validation.valid:
            raise ValueError(
                "captured Twitch VOD window failed validation: " + ",".join(validation.error_codes),
            )
        staging.replace(dataset_dir)
    print(dataset_dir)
    return dataset_dir


def validate_dataset(args: argparse.Namespace) -> dict[str, Any]:
    result = DatasetValidator().validate(args.dataset)
    payload = {
        "valid": result.valid,
        "errors": result.errors,
        "event_count": len(result.events),
        "manifest": result.manifest,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if not result.valid:
        raise ValueError("dataset validation failed")
    return payload


def clean_dataset(args: argparse.Namespace) -> list[Path]:
    """Run the strict production cleaning pipeline and close its LLM client."""
    processor = create_deepseek_semantic_processor(
        args.config,
        profile=args.llm_profile,
    )

    async def run() -> list[Path]:
        try:
            return await publish_clean_datasets(
                args.dataset,
                args.output_root,
                processor=processor,
                options=CleanOptions(
                    profile=args.profile,
                    target_language=args.target_language,
                    synthetic_ratio=args.synthetic_ratio,
                    seed=args.seed,
                    derive_medium=args.derive_medium,
                    medium_rate=args.medium_rate,
                ),
                cache_path=Path("artifacts/livestream-eval/cleaning-cache")
                / f"{args.dataset.name}.jsonl",
                evidence_root=Path("artifacts/livestream-eval"),
            )
        finally:
            await processor.close()

    paths = asyncio.run(run())
    print(json.dumps({"datasets": [str(path) for path in paths]}, ensure_ascii=False))
    return paths


def replay_dataset(args: argparse.Namespace) -> dict[str, Any]:
    output = args.output or Path("artifacts/livestream-eval") / f"{args.dataset.name}-{args.mode}"
    result = asyncio.run(_run_replay(args, output))
    print(json.dumps({"output": str(output), "passed": result["hard_gates"]["passed"]}))
    return result


def report_run(args: argparse.Namespace) -> dict[str, Any]:
    report = write_report(
        args.run_dir,
        scores_path=args.scores,
        safety_assessment_path=args.safety_assessment,
        seed=args.seed,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture":
            capture_dataset(args)
        elif args.command == "clean":
            clean_dataset(args)
        elif args.command == "validate":
            validate_dataset(args)
        elif args.command == "replay":
            replay_dataset(args)
        else:
            report_run(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"livestream-eval: {exc}", file=sys.stderr)
        return 2
    return 0


def _load_processor(
    specification: str,
) -> Callable[[ReplyCandidate], Awaitable[str | None]]:
    try:
        module_name, attribute = specification.split(":", 1)
        callback = getattr(importlib.import_module(module_name), attribute)
    except (AttributeError, ImportError, ValueError) as exc:
        raise ValueError("processor must resolve from module:function") from exc

    async def invoke(candidate: ReplyCandidate) -> str | None:
        result = callback(candidate)
        if inspect.isawaitable(result):
            result = await result
        return None if result is None else str(result)

    return invoke


async def _run_replay(args: argparse.Namespace, output: Path) -> dict[str, Any]:
    socket_processor = None
    processor: Callable[[ReplyCandidate], Awaitable[str | None]] | None
    if args.mode == "full" and not args.processor:
        socket_processor = SocketIOFullStackProcessor(args.server_url)
        await socket_processor.connect()
        processor = socket_processor.process
    else:
        processor = _load_processor(args.processor) if args.processor else None
    resource_sampler: Callable[[], float] | None = None
    resource_identity: str | None = None
    if args.mode == "full" and args.resource_pid is None:
        resource_sampler, resource_identity = _docker_resource_sampler(args.resource_container)
    safety_assessment = (
        _load_safety_assessment(args.safety_assessment) if args.safety_assessment else None
    )
    try:
        return await EvaluationRunner(
            args.dataset,
            output,
            mode=args.mode,
            speed=args.speed,
            burst_windows=default_bursts(args.burst_profile == "high"),
            reply_processor=processor,
            resource_pid=args.resource_pid,
            resource_sampler=resource_sampler,
            resource_identity=resource_identity,
            safety_assessment=safety_assessment,
            duration_seconds=_resolve_duration_seconds(args.mode, args.duration_minutes),
        ).run()
    finally:
        if socket_processor is not None:
            await socket_processor.close()


def _resolve_duration_seconds(mode: str, duration_minutes: float | None) -> float | None:
    """Resolve the source-timeline window without shortening transport coverage."""
    if duration_minutes is None:
        return 90 * 60 if mode == "full" else None
    if duration_minutes <= 0:
        raise ValueError("duration-minutes must be positive")
    return duration_minutes * 60


def _docker_resource_sampler(service: str) -> tuple[Callable[[], float], str]:
    """Return a sampler for the running Animetta container, never a build/start action."""
    result = subprocess.run(
        ["docker", "compose", "ps", "-q", service],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    container_id = result.stdout.strip()
    if not container_id:
        raise RuntimeError(f"resource container is not running: {service}")

    def sample() -> float:
        stats = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", container_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        payload = json.loads(stats.stdout.strip())
        usage = str(payload.get("MemUsage", "")).split("/", 1)[0].strip()
        return _parse_memory_megabytes(usage)

    return sample, f"docker:{service}:{container_id[:12]}"


def _parse_memory_megabytes(value: str) -> float:
    match = re.fullmatch(r"\s*([0-9]+(?:\.[0-9]+)?)\s*([KMGT]?i?B)\s*", value, re.IGNORECASE)
    if match is None:
        raise RuntimeError(f"unrecognized docker memory value: {value}")
    amount = float(match.group(1))
    unit = match.group(2).casefold()
    factors = {
        "b": 1 / (1024 * 1024),
        "kb": 1 / 1024,
        "kib": 1 / 1024,
        "mb": 1.0,
        "mib": 1.0,
        "gb": 1024.0,
        "gib": 1024.0,
        "tb": 1024.0 * 1024.0,
        "tib": 1024.0 * 1024.0,
    }
    return amount * factors[unit]


def _load_safety_assessment(path: Path) -> dict[str, Any]:
    return load_safety_assessment(path, require_assessed=True)


if __name__ == "__main__":
    raise SystemExit(main())
