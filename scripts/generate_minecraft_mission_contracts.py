#!/usr/bin/env python3
"""Generate the versioned adaptive Minecraft mission contract bundle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from animetta.tools.minecraft.mission.schema import (  # noqa: E402
    build_golden_fixture,
    build_schema_bundle,
    schema_digest,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    target = ROOT / "contracts" / "minecraft" / "mission" / "v1"
    bundle = build_schema_bundle()
    _write_json(target / "schema.json", bundle)
    (target / "schema.sha256").write_text(schema_digest(bundle) + "\n", encoding="utf-8")
    _write_json(target / "fixtures" / "golden.json", build_golden_fixture())
    print(f"Generated adaptive mission contract v1 under {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
