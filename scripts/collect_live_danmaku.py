#!/usr/bin/env python3
"""Collect normalized Bilibili live-room danmaku to local CSV and JSONL files."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

main = importlib.import_module("animetta.acceptance.live_danmaku_collector").main


if __name__ == "__main__":
    raise SystemExit(main())
