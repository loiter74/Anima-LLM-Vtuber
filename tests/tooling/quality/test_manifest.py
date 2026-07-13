from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tooling.quality.manifest import load_catalog
from tooling.quality.models import Catalog

ROOT = Path(__file__).resolve().parents[3]


def _valid_catalog() -> dict:
    return {
        "schema_version": 1,
        "groups": {
            "backend-unit": {
                "domain": "backend",
                "kind": "unit",
                "runner": "pytest",
                "isolation": "hermetic",
                "targets": ["tests/core"],
                "include_in_full": True,
            },
            "repository-full": {
                "domain": "repository",
                "kind": "contract",
                "runner": "pytest",
                "isolation": "hermetic",
                "targets": ["tests"],
                "depends_on": ["backend-unit"],
                "include_in_full": True,
            },
        },
        "components": {
            "backend-core": {
                "domain": "backend",
                "paths": ["src/animetta/core/**"],
                "direct_groups": ["backend-unit"],
                "impacts": [],
                "risk": "normal",
            }
        },
        "fallbacks": {
            "backend": ["backend-unit"],
            "frontend": ["repository-full"],
            "repository": ["repository-full"],
        },
    }


def test_catalog_rejects_unknown_enum_value() -> None:
    data = _valid_catalog()
    data["groups"]["backend-unit"]["isolation"] = "sometimes-external"

    with pytest.raises(ValidationError, match="isolation"):
        Catalog.model_validate(data)


def test_catalog_rejects_unknown_component_group() -> None:
    data = _valid_catalog()
    data["components"]["backend-core"]["direct_groups"] = ["missing-group"]

    with pytest.raises(ValidationError, match="missing-group"):
        Catalog.model_validate(data)


def test_catalog_rejects_unknown_fallback_group() -> None:
    data = _valid_catalog()
    data["fallbacks"]["backend"] = ["missing-fallback"]

    with pytest.raises(ValidationError, match="missing-fallback"):
        Catalog.model_validate(data)


def test_catalog_rejects_execution_dependency_cycle() -> None:
    data = _valid_catalog()
    data["groups"]["backend-unit"]["depends_on"] = ["repository-full"]

    with pytest.raises(ValidationError, match="dependency cycle"):
        Catalog.model_validate(data)


def test_catalog_rejects_unsafe_group_and_component_ids() -> None:
    unsafe_group = _valid_catalog()
    unsafe_group["groups"]["../escape"] = unsafe_group["groups"].pop("backend-unit")

    with pytest.raises(ValidationError, match="safe kebab-case"):
        Catalog.model_validate(unsafe_group)

    unsafe_component = _valid_catalog()
    unsafe_component["components"]["backend/core"] = unsafe_component[
        "components"
    ].pop("backend-core")

    with pytest.raises(ValidationError, match="safe kebab-case"):
        Catalog.model_validate(unsafe_component)


def test_catalog_rejects_artifact_paths_outside_repository() -> None:
    data = _valid_catalog()
    data["groups"]["backend-unit"]["artifacts"] = ["../outside.xml"]

    with pytest.raises(ValidationError, match="repository-relative"):
        Catalog.model_validate(data)


def test_load_catalog_validates_yaml_and_returns_stable_hash(tmp_path: Path) -> None:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
groups:
  backend-unit:
    domain: backend
    kind: unit
    runner: pytest
    isolation: hermetic
    targets: [tests/core]
    include_in_full: true
  repository-full:
    domain: repository
    kind: contract
    runner: pytest
    isolation: hermetic
    targets: [tests]
    depends_on: [backend-unit]
    include_in_full: true
components:
  backend-core:
    domain: backend
    paths: [src/animetta/core/**]
    direct_groups: [backend-unit]
    impacts: []
    risk: normal
fallbacks:
  backend: [backend-unit]
  frontend: [repository-full]
  repository: [repository-full]
""".strip(),
        encoding="utf-8",
    )

    first = load_catalog(manifest)
    second = load_catalog(manifest)

    assert first.catalog.schema_version == 1
    assert first.manifest_hash == second.manifest_hash
    assert len(first.manifest_hash) == 64


def test_repository_catalog_covers_runtime_environments() -> None:
    loaded = load_catalog(ROOT / "tooling" / "quality.yml")

    runners = {group.runner.value for group in loaded.catalog.groups.values()}
    capabilities = {
        capability.value
        for group in loaded.catalog.groups.values()
        for capability in group.capabilities
    }

    assert {"pytest", "pnpm", "playwright", "docker"}.issubset(runners)
    assert {"browser", "docker"}.issubset(capabilities)
    assert set(loaded.catalog.fallbacks.model_dump()) == {
        "backend",
        "frontend",
        "repository",
    }
