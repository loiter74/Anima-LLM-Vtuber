"""Measure the authenticated Windows host TTS streaming contract."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TEXT = "你好，今天也请多关照。我们一起把这件事情做好吧。"
HOST_MODEL = "Qwen3-TTS-1.7B-Base"
HOST_VOICE = "tosaka-rin-cn"


def _synthesize_once(
    client: httpx.Client,
    *,
    url: str,
    token: str,
    text: str,
) -> dict[str, float | int]:
    started = time.perf_counter()
    first_audio_seconds: float | None = None
    audio_bytes = 0
    with client.stream(
        "POST",
        f"{url.rstrip('/')}/v1/audio/speech",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "model": HOST_MODEL,
            "voice": HOST_VOICE,
            "input": text,
            "language": "Chinese",
            "response_format": "wav",
            "stream": True,
        },
    ) as response:
        response.raise_for_status()
        if response.headers.get("content-type", "").split(";", 1)[0] != "audio/pcm":
            raise RuntimeError("Host TTS did not return PCM")
        if response.headers.get("x-animetta-audio-format") != "pcm_s16le":
            raise RuntimeError("Host TTS returned an unexpected PCM format")
        if response.headers.get("x-animetta-sample-rate") != "24000":
            raise RuntimeError("Host TTS returned an unexpected sample rate")
        if response.headers.get("x-animetta-channels") != "1":
            raise RuntimeError("Host TTS returned an unexpected channel count")
        for chunk in response.iter_raw():
            if not chunk:
                continue
            if first_audio_seconds is None:
                first_audio_seconds = time.perf_counter() - started
            audio_bytes += len(chunk)

    elapsed = time.perf_counter() - started
    if first_audio_seconds is None or audio_bytes == 0:
        raise RuntimeError("Host TTS returned empty audio")
    if audio_bytes % 2:
        raise RuntimeError("Host TTS returned an odd PCM16 byte count")
    audio_seconds = audio_bytes / (24_000 * 2)
    return {
        "first_audio_seconds": first_audio_seconds,
        "rtf": elapsed / audio_seconds,
        "audio_seconds": audio_seconds,
        "audio_bytes": audio_bytes,
    }


def benchmark(
    *,
    url: str,
    token: str,
    text: str,
    warmups: int,
    runs: int,
) -> dict[str, Any]:
    timeout = httpx.Timeout(connect=5, read=180, write=10, pool=5)
    with httpx.Client(timeout=timeout) as client:
        for _ in range(warmups):
            _synthesize_once(client, url=url, token=token, text=text)
        samples = [_synthesize_once(client, url=url, token=token, text=text) for _ in range(runs)]

    first_audio = [float(sample["first_audio_seconds"]) for sample in samples]
    rtf = [float(sample["rtf"]) for sample in samples]
    return {
        "contract": {
            "sample_rate": 24000,
            "channels": 1,
            "sample_format": "pcm_s16le",
        },
        "warmups": warmups,
        "runs": runs,
        "first_audio_seconds": {
            "max": max(first_audio),
            "median": statistics.median(first_audio),
        },
        "rtf": {
            "max": max(rtf),
            "median": statistics.median(rtf),
        },
        "samples": samples,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8767")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--max-first-audio", type=float, default=0.75)
    parser.add_argument("--max-rtf", type=float, default=0.35)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.warmups < 0 or args.runs < 1:
        raise SystemExit("warmups must be non-negative and runs must be positive")
    load_dotenv(ROOT / ".env", override=False)
    token = os.getenv("QWEN_TTS_API_KEY", "").strip()
    if not token:
        raise SystemExit("QWEN_TTS_API_KEY is not configured")

    result = benchmark(
        url=args.url,
        token=token,
        text=args.text,
        warmups=args.warmups,
        runs=args.runs,
    )
    passed = (
        result["first_audio_seconds"]["max"] <= args.max_first_audio
        and result["rtf"]["max"] <= args.max_rtf
    )
    result["thresholds"] = {
        "max_first_audio_seconds": args.max_first_audio,
        "max_rtf": args.max_rtf,
    }
    result["passed"] = passed
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
