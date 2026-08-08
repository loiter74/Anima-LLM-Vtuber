#!/usr/bin/env python3
"""Report or enforce Minecraft control-plane architecture boundaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tooling.quality.minecraft_architecture import audit_repository, render_report


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--report", action="store_true", help="report findings without failing")
    mode.add_argument("--check", action="store_true", help="fail when findings remain")
    args = parser.parse_args()

    violations = audit_repository(ROOT)
    print(render_report(violations))
    return 1 if args.check and violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
