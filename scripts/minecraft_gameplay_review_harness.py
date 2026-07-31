"""Run the loopback-only Minecraft gameplay review harness."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import uvicorn

from animetta.acceptance.minecraft_gameplay_review import (
    create_real_harness,
    create_review_app,
)

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    token = os.environ.get("ANIMETTA_REVIEW_TOKEN", "").strip()
    if not token:
        raise SystemExit("Required review credential is not configured")
    artifact_dir = Path(tempfile.mkdtemp(prefix="animetta-minecraft-review-"))
    harness = create_real_harness(
        repository_dir=ROOT,
        token=token,
        artifact_dir=artifact_dir,
    )
    uvicorn.run(
        create_review_app(harness),
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
