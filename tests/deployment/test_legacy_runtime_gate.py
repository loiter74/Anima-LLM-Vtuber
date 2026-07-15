from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/config/fixtures/legacy_runtime_selectors.json"
TEXT_SUFFIXES = {
    ".dockerfile",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}


def _contract() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _source_files(root_name: str) -> list[Path]:
    root = ROOT / root_name
    if root.is_file():
        return [root]
    if not root.exists():
        return []
    return [
        path
        for path in root.rglob("*")
        if path.is_file()
        and (
            path.suffix.lower() in TEXT_SUFFIXES
            or path.name.startswith("Dockerfile")
            or path.name.startswith(".env.")
        )
        and not any(part in {"node_modules", "dist", ".git"} for part in path.parts)
    ]


def test_forbidden_runtime_manifests_are_absent() -> None:
    for relative in _contract()["forbidden_runtime_files"]:
        assert not (ROOT / relative).exists(), relative


def test_fixture_driven_source_gate_rejects_legacy_selectors() -> None:
    violations: list[str] = []
    for rule in _contract()["source_rules"]:
        excluded = {item.replace("\\", "/") for item in rule.get("exclude", [])}
        for root_name in rule["roots"]:
            for path in _source_files(root_name):
                relative = path.relative_to(ROOT).as_posix()
                if relative in excluded:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
                for pattern in rule["forbidden_patterns"]:
                    if pattern in text:
                        violations.append(f"{relative}: {pattern}")

    assert violations == []


def test_only_canonical_manifest_is_named_as_application_runtime_config() -> None:
    assert (ROOT / "config/animetta.yaml").is_file()
    assert not (ROOT / "src/animetta/config/app.py").exists()


def test_deployment_and_manifest_sources_do_not_contain_literal_credentials() -> None:
    paths = [
        ROOT / "config/animetta.yaml",
        ROOT / "docker-compose.yml",
        ROOT / "docker-compose.cpu.yml",
        ROOT / "docker-compose.core.yml",
        ROOT / "fly.toml",
        ROOT / "zeabur.json",
    ]
    suspicious_prefixes = ("sk-", "Bearer ", "hf_")
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for prefix in suspicious_prefixes:
            assert prefix not in text, f"literal credential prefix in {path.name}"
