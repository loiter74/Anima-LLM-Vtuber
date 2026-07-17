#!/usr/bin/env python3
"""Generate the stage-one anonymous low-latency emotive TTS audition."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if __name__ == "__main__":
    cli = import_module("animetta.acceptance.tts_audition.cli")
    raise SystemExit(cli.main())
