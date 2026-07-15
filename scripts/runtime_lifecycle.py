"""Cross-platform lifecycle operations for persistent Qwen and Animetta."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QWEN_COMPOSE = ["docker", "compose", "-f", "docker-compose.qwen.yml"]
OPERATIONS = (
    "qwen-build",
    "qwen-up",
    "qwen-deploy",
    "qwen-stop",
    "qwen-destroy",
    "anima-up",
    "anima-down",
)


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def _preflight(*, wait: bool) -> list[str]:
    command = [sys.executable, "scripts/qwen_preflight.py"]
    if wait:
        command.append("--wait")
    return command


def _qwen_build_fingerprint() -> str:
    from tooling.quality.docker_plan import fingerprint_docker_scopes
    from tooling.quality.fingerprint import FingerprintContext
    from tooling.quality.manifest import load_catalog

    loaded = load_catalog(ROOT / "tooling" / "quality.yml")
    return fingerprint_docker_scopes(loaded.catalog, FingerprintContext(ROOT))["qwen-tts"]


def _qwen_build_command() -> list[str]:
    return [
        *QWEN_COMPOSE,
        "build",
        "--build-arg",
        f"QWEN_TTS_BUILD_FINGERPRINT={_qwen_build_fingerprint()}",
        "qwen-tts",
    ]


def run_operation(operation: str) -> None:
    """Execute one explicit lifecycle operation."""
    if operation == "qwen-build":
        _run(_qwen_build_command())
    elif operation == "qwen-up":
        _run(
            [
                *QWEN_COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--no-recreate",
                "qwen-tts",
            ]
        )
        _run(_preflight(wait=True))
    elif operation == "qwen-deploy":
        _run(_qwen_build_command())
        _run(
            [
                *QWEN_COMPOSE,
                "up",
                "-d",
                "--no-build",
                "--force-recreate",
                "qwen-tts",
            ]
        )
        _run(_preflight(wait=True))
    elif operation == "qwen-stop":
        _run([*QWEN_COMPOSE, "stop", "qwen-tts"])
    elif operation == "qwen-destroy":
        _run([*QWEN_COMPOSE, "down", "--remove-orphans"])
    elif operation == "anima-up":
        _run(_preflight(wait=False))
        _run(["docker", "compose", "build", "animetta"])
        _run(["docker", "compose", "up", "-d", "--no-build", "animetta"])
    elif operation == "anima-down":
        _run(["docker", "compose", "down", "--remove-orphans"])
    else:
        raise ValueError(f"Unknown lifecycle operation: {operation}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=OPERATIONS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    run_operation(args.operation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
