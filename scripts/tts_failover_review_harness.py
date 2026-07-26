"""Run the loopback-only OBS TTS failover review harness."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

from animetta.acceptance.tts_failover_review import create_real_harness, create_review_app

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--fallback-url", default="http://127.0.0.1:8767")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT / ".env", override=False)
    token = os.environ.get("ANIMETTA_REVIEW_TOKEN", "").strip()
    fallback_token = os.environ.get("QWEN_TTS_API_KEY", "").strip()
    if not token or not fallback_token:
        raise SystemExit("Required review credentials are not configured")
    artifact_dir = Path(tempfile.mkdtemp(prefix="animetta-tts-failover-"))
    harness = create_real_harness(
        port=args.port,
        token=token,
        fallback_token=fallback_token,
        artifact_dir=artifact_dir,
        fallback_url=args.fallback_url,
    )
    app = create_review_app(harness)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="warning",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
