from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_ruff_formatter_normalizes_python_line_endings() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["tool"]["ruff"]["format"]["line-ending"] == "lf"
