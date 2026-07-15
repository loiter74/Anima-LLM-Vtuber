from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAINTAINED_PYTHON_ROOTS = {"src", "tooling", "scripts", "evaluations", "tests"}


def _load_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_ruff_formatter_normalizes_python_line_endings() -> None:
    config = _load_config()

    assert config["tool"]["ruff"]["format"]["line-ending"] == "lf"


def test_ruff_does_not_hide_undefined_names_by_package() -> None:
    config = _load_config()
    per_file_ignores = config["tool"]["ruff"]["lint"].get("per-file-ignores", {})

    broad_undefined_name_ignores = {
        pattern: rules
        for pattern, rules in per_file_ignores.items()
        if "F821" in rules and any(marker in pattern for marker in ("/**", "/**/*.py"))
    }

    assert broad_undefined_name_ignores == {}


def test_ruff_enforces_public_interface_annotations() -> None:
    config = _load_config()
    selected_rules = set(config["tool"]["ruff"]["lint"]["select"])

    assert {"ANN001", "ANN201"} <= selected_rules


def test_mypy_does_not_hide_package_errors() -> None:
    config = _load_config()
    overrides = config["tool"]["mypy"].get("overrides", [])

    ignored_modules = [
        override.get("module") for override in overrides if override.get("ignore_errors")
    ]

    assert ignored_modules == []


def test_mypy_uses_repository_relative_package_bases() -> None:
    config = _load_config()

    assert config["tool"]["mypy"]["explicit_package_bases"] is True


def test_ruff_keeps_every_maintained_python_root_in_scope() -> None:
    config = _load_config()
    ruff = config["tool"]["ruff"]
    excluded = {*ruff.get("exclude", []), *ruff.get("extend-exclude", [])}

    hidden_roots = {
        root
        for root in MAINTAINED_PYTHON_ROOTS
        if any(pattern == root or pattern.startswith(f"{root}/") for pattern in excluded)
    }

    assert hidden_roots == set()
