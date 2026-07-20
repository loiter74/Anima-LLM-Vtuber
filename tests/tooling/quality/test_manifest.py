from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tooling.quality.manifest import load_catalog
from tooling.quality.models import Catalog

ROOT = Path(__file__).resolve().parents[3]


def test_tooling_quality_test_modules_do_not_collide_with_other_test_modules() -> None:
    tooling_root = ROOT / "tests" / "tooling" / "quality"
    tooling_names = {path.name for path in tooling_root.glob("test_*.py")}
    other_names = {
        path.name
        for path in (ROOT / "tests").rglob("test_*.py")
        if tooling_root not in path.parents
    }

    assert tooling_names.isdisjoint(other_names), sorted(tooling_names & other_names)


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


def _catalog_with_acceleration() -> dict:
    data = _valid_catalog()
    data["input_sets"] = {
        "quality-engine": {
            "paths": ["tooling/quality/**", "tooling/quality.yml"],
        },
        "python-toolchain": {
            "paths": ["pyproject.toml", "requirements*.txt"],
        },
    }
    data["default_input_sets"] = ["quality-engine"]
    data["scheduler"] = {
        "max_workers": 4,
        "max_weight": 4,
        "max_heavy": 1,
        "max_exclusive": 1,
    }
    data["groups"]["backend-unit"].update(
        {
            "cacheable": True,
            "resource_class": "cpu",
            "resource_weight": 2,
            "input_sets": ["python-toolchain"],
        }
    )
    data["groups"]["repository-full"].update(
        {
            "cacheable": True,
            "resource_class": "heavy",
            "resource_weight": 4,
            "input_sets": ["python-toolchain"],
            "covers": ["backend-unit"],
        }
    )
    data["docker_watch_paths"] = [
        "Dockerfile*",
        "docker-compose*.yml",
        "docker/**",
        "requirements*.txt",
    ]
    data["docker_scopes"] = {
        "animetta": {
            "service": "animetta",
            "compose_file": "docker-compose.yml",
            "paths": ["Dockerfile", "requirements-core.txt", "src/animetta/**"],
            "environment_identity_fields": ["ANIMETTA_PROFILE", "DEEPSEEK_API_KEY"],
        },
        "qwen-tts": {
            "service": "qwen-tts",
            "compose_file": "docker-compose.qwen.yml",
            "paths": [
                "Dockerfile.qwen-tts",
                "requirements-qwen-tts.txt",
                "src/animetta_qwen_tts/**",
            ],
            "environment_identity_fields": ["QWEN_TTS_API_KEY", "QWEN_TTS_URL"],
        },
    }
    return data


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
    unsafe_component["components"]["backend/core"] = unsafe_component["components"].pop(
        "backend-core"
    )

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


def test_repository_catalog_covers_full_python_standard_scope() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    expected_targets = ("src", "tooling", "scripts", "evaluations", "tests")

    assert catalog.groups["python-format"].runner.value == "ruff-format"
    assert catalog.groups["python-format"].targets == expected_targets
    assert catalog.groups["python-format"].include_in_full is True
    assert catalog.groups["backend-static"].targets == expected_targets
    assert catalog.groups["backend-support-typecheck"].targets == (
        "tooling/quality",
        "scripts",
        "evaluations",
    )

    for component_id in {
        "backend-core",
        "backend-config",
        "orchestration-server",
        "orchestration-graph",
        "backend-services",
        "backend-memory",
        "backend-tools",
        "backend-observability",
    }:
        assert {
            "python-format",
            "backend-static",
            "backend-typecheck",
        }.issubset(catalog.components[component_id].direct_groups)

    assert {
        "python-format",
        "backend-static",
        "backend-support-typecheck",
    }.issubset(catalog.components["quality-control-plane"].direct_groups)


def test_repository_catalog_has_a_dedicated_acceptance_audition_gate() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    group = catalog.groups["backend-acceptance-unit"]
    component = catalog.components["backend-acceptance"]

    assert group.runner.value == "pytest"
    assert group.targets == ("tests/acceptance",)
    assert group.cacheable is True
    assert component.paths == (
        "src/animetta/acceptance/**",
        "tests/acceptance/**",
        "scripts/tts_audition.py",
    )
    assert {
        "backend-acceptance-unit",
        "python-format",
        "backend-static",
        "backend-typecheck",
        "backend-support-typecheck",
        "backend-deadcode",
        "security-secrets",
    }.issubset(component.direct_groups)
    assert "backend-acceptance-unit" in catalog.groups["backend-full"].covers
    assert "scripts/README.md" in catalog.components["documentation"].paths
    assert ".gitignore" in catalog.components["repository-governance"].paths


def test_repository_catalog_has_frontend_lint_and_format_gates() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog

    assert catalog.groups["frontend-lint"].runner.value == "pnpm"
    assert catalog.groups["frontend-lint"].args == ("lint",)
    assert catalog.groups["frontend-lint"].include_in_full is True
    assert catalog.groups["frontend-format"].runner.value == "pnpm"
    assert catalog.groups["frontend-format"].args == ("format:check",)
    assert catalog.groups["frontend-format"].include_in_full is True

    gated_paths = {
        path
        for component in catalog.components.values()
        if {"frontend-lint", "frontend-format"}.issubset(component.direct_groups)
        for path in component.paths
    }
    assert {
        "frontend/src/**",
        "frontend/electron/**",
        "frontend/scripts/**",
    }.issubset(gated_paths)


def test_python_source_boundary_rejects_ungated_javascript() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    component = catalog.components["python-source-boundary"]

    assert component.paths == (
        "src/**/*.js",
        "src/**/*.mjs",
        "src/**/*.cjs",
        "src/**/*.ts",
    )
    assert component.direct_groups == ("operational-source-contract",)


def test_every_compose_variant_has_a_canonical_contract_gate() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    expected = {
        "docker-compose-contract": (
            "compose",
            "-f",
            "docker-compose.yml",
            "config",
            "--quiet",
        ),
        "docker-compose-cpu-contract": (
            "compose",
            "-f",
            "docker-compose.cpu.yml",
            "config",
            "--quiet",
        ),
        "docker-compose-core-contract": (
            "compose",
            "-f",
            "docker-compose.core.yml",
            "config",
            "--quiet",
        ),
        "docker-compose-selftest-contract": (
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.selftest.yml",
            "config",
            "--quiet",
        ),
        "docker-compose-qwen-contract": (
            "compose",
            "--env-file",
            ".env.example",
            "-f",
            "docker-compose.qwen.yml",
            "config",
            "--quiet",
        ),
    }

    for group_id, expected_args in expected.items():
        group = catalog.groups[group_id]
        assert group.runner.value == "docker"
        assert group.args == expected_args
        assert group.include_in_full is True

    assert set(expected).issubset(catalog.components["docker-infrastructure"].direct_groups)


def test_repository_catalog_has_dead_code_and_duplication_gates() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog

    assert catalog.groups["backend-deadcode"].runner.value == "vulture"
    assert catalog.groups["backend-deadcode"].include_in_full is True
    assert catalog.groups["frontend-deadcode"].args == ("deadcode",)
    assert catalog.groups["frontend-deadcode"].include_in_full is True
    assert catalog.groups["frontend-duplicates"].args == ("duplicates:check",)
    assert catalog.groups["frontend-duplicates"].include_in_full is True


def test_backend_full_bounds_parallel_workers_for_cross_platform_stability() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    args = catalog.groups["backend-full"].args

    worker_flag = args.index("-n")
    assert args[worker_flag + 1] == "8"


def test_repository_catalog_has_operational_source_contract() -> None:
    catalog = load_catalog(ROOT / "tooling" / "quality.yml").catalog
    group = catalog.groups["operational-source-contract"]

    assert group.runner.value == "python"
    assert group.entrypoint == "scripts/check_source_standards.py"
    assert group.include_in_full is True
    assert group.cacheable is True

    operational_paths = {
        path
        for component in catalog.components.values()
        if "operational-source-contract" in component.direct_groups
        for path in component.paths
    }
    assert {
        "scripts/check_source_standards.py",
        "Dockerfile*",
        "**/Dockerfile*",
        "**/*.sh",
        "**/*.ps1",
        "**/*.bat",
        "**/*.cmd",
        "**/*.yaml",
        "**/*.yml",
        "**/*.json",
        "**/*.toml",
    }.issubset(operational_paths)


def test_catalog_accepts_valid_acceleration_metadata() -> None:
    catalog = Catalog.model_validate(_catalog_with_acceleration())

    assert catalog.default_input_sets == ("quality-engine",)
    assert catalog.input_sets["python-toolchain"].paths == (
        "pyproject.toml",
        "requirements*.txt",
    )
    assert catalog.scheduler.max_workers == 4
    assert catalog.groups["backend-unit"].cacheable is True
    assert catalog.groups["backend-unit"].resource_class.value == "cpu"
    assert catalog.groups["repository-full"].covers == ("backend-unit",)
    assert catalog.docker_scopes["qwen-tts"].service == "qwen-tts"
    assert catalog.docker_scopes["qwen-tts"].compose_file == "docker-compose.qwen.yml"
    assert catalog.docker_scopes["qwen-tts"].environment_identity_fields == (
        "QWEN_TTS_API_KEY",
        "QWEN_TTS_URL",
    )


def test_catalog_rejects_docker_scope_compose_file_outside_repository() -> None:
    data = _catalog_with_acceleration()
    data["docker_scopes"]["qwen-tts"]["compose_file"] = "../docker-compose.yml"

    with pytest.raises(ValidationError, match="repository-relative"):
        Catalog.model_validate(data)


def test_catalog_rejects_cacheable_non_hermetic_group() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["backend-unit"]["isolation"] = "service"

    with pytest.raises(ValidationError, match="cacheable.*hermetic"):
        Catalog.model_validate(data)


def test_catalog_rejects_unknown_group_input_set() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["backend-unit"]["input_sets"] = ["missing-inputs"]

    with pytest.raises(ValidationError, match="missing-inputs"):
        Catalog.model_validate(data)


@pytest.mark.parametrize("weight", [0, 5])
def test_catalog_rejects_group_weight_outside_scheduler_budget(weight: int) -> None:
    data = _catalog_with_acceleration()
    data["groups"]["backend-unit"]["resource_weight"] = weight

    with pytest.raises(ValidationError, match="resource_weight"):
        Catalog.model_validate(data)


@pytest.mark.parametrize(
    ("covering", "covered", "message"),
    [
        ("backend-unit", "missing-group", "missing-group"),
        ("backend-unit", "backend-unit", "cover itself"),
    ],
)
def test_catalog_rejects_unknown_or_self_coverage(
    covering: str,
    covered: str,
    message: str,
) -> None:
    data = _catalog_with_acceleration()
    data["groups"][covering]["covers"] = [covered]

    with pytest.raises(ValidationError, match=message):
        Catalog.model_validate(data)


def test_catalog_rejects_coverage_cycle() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["backend-unit"]["covers"] = ["repository-full"]

    with pytest.raises(ValidationError, match="coverage cycle"):
        Catalog.model_validate(data)


def test_catalog_rejects_incompatible_coverage_runner() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["repository-full"]["runner"] = "python"
    data["groups"]["repository-full"]["entrypoint"] = "scripts/check.py"
    data["groups"]["repository-full"].pop("targets")

    with pytest.raises(ValidationError, match="compatible runner"):
        Catalog.model_validate(data)


@pytest.mark.parametrize("mutation", ["required", "isolation", "capabilities"])
def test_catalog_rejects_coverage_with_weaker_execution_contract(mutation: str) -> None:
    data = _catalog_with_acceleration()
    covering = data["groups"]["repository-full"]
    covered = data["groups"]["backend-unit"]
    if mutation == "required":
        covering["required"] = False
    elif mutation == "isolation":
        covered["cacheable"] = False
        covered["isolation"] = "service"
    else:
        covered["cacheable"] = False
        covered["capabilities"] = ["network"]

    with pytest.raises(ValidationError, match="coverage.*contract"):
        Catalog.model_validate(data)


def test_catalog_rejects_pytest_coverage_that_does_not_cover_target() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["repository-full"]["targets"] = ["tests/services"]

    with pytest.raises(ValidationError, match="does not cover target"):
        Catalog.model_validate(data)


def test_catalog_rejects_pytest_coverage_with_narrower_selection_filter() -> None:
    data = _catalog_with_acceleration()
    data["groups"]["repository-full"]["args"] = ["-q", "-k", "smoke"]

    with pytest.raises(ValidationError, match="selection filters"):
        Catalog.model_validate(data)


def test_catalog_accepts_matching_pytest_marker_filter_for_coverage() -> None:
    data = _catalog_with_acceleration()
    marker_args = ["-m", "not slow and not integration"]
    data["groups"]["backend-unit"]["args"] = marker_args
    data["groups"]["repository-full"]["args"] = marker_args

    Catalog.model_validate(data)


def test_catalog_rejects_incomplete_or_unsafe_docker_scope() -> None:
    no_paths = _catalog_with_acceleration()
    no_paths["docker_scopes"]["animetta"]["paths"] = []
    with pytest.raises(ValidationError, match="paths"):
        Catalog.model_validate(no_paths)

    unsafe_service = _catalog_with_acceleration()
    unsafe_service["docker_scopes"]["animetta"]["service"] = "../animetta"
    with pytest.raises(ValidationError, match="safe kebab-case"):
        Catalog.model_validate(unsafe_service)


def test_catalog_rejects_secret_or_escaping_fingerprint_inputs() -> None:
    secret = _catalog_with_acceleration()
    secret["input_sets"]["python-toolchain"]["paths"] = [".env"]
    with pytest.raises(ValidationError, match="secret"):
        Catalog.model_validate(secret)

    escaping = _catalog_with_acceleration()
    escaping["docker_scopes"]["qwen-tts"]["paths"] = ["../outside"]
    with pytest.raises(ValidationError, match="repository-relative"):
        Catalog.model_validate(escaping)
