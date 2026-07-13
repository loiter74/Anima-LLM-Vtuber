from __future__ import annotations

import re
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Domain(StrEnum):
    BACKEND = "backend"
    FRONTEND = "frontend"
    REPOSITORY = "repository"


class VerificationKind(StrEnum):
    LINT = "lint"
    TYPECHECK = "typecheck"
    UNIT = "unit"
    CONTRACT = "contract"
    SMOKE = "smoke"
    BUILD = "build"
    INTEGRATION = "integration"
    E2E = "e2e"


class Runner(StrEnum):
    RUFF = "ruff"
    MYPY = "mypy"
    PYTEST = "pytest"
    PYTHON = "python"
    PNPM = "pnpm"
    VITEST = "vitest"
    PLAYWRIGHT = "playwright"
    DOCKER = "docker"


class Isolation(StrEnum):
    HERMETIC = "hermetic"
    SERVICE = "service"
    EXTERNAL = "external"


class Capability(StrEnum):
    BROWSER = "browser"
    DOCKER = "docker"
    NETWORK = "network"
    GPU = "gpu"


class Risk(StrEnum):
    NORMAL = "normal"
    HIGH = "high"
    GLOBAL = "global"


class Tier(StrEnum):
    QUICK = "quick"
    AFFECTED = "affected"
    FULL = "full"
    NIGHTLY = "nightly"


class ChangeStatus(StrEnum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


class ResultStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AggregateStatus(StrEnum):
    PASSED = "passed"
    DEGRADED = "degraded"
    FAILED = "failed"


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Change(FrozenModel):
    path: str
    status: ChangeStatus
    old_path: str | None = None


class ChangeSet(FrozenModel):
    changes: tuple[Change, ...]
    source: Literal["paths", "worktree", "range"]
    base_sha: str | None = None
    head_sha: str | None = None


def _validate_relative_posix(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"path must be repository-relative: {value!r}")
    return normalized


class VerificationGroup(FrozenModel):
    domain: Domain
    kind: VerificationKind
    runner: Runner
    isolation: Isolation = Isolation.HERMETIC
    targets: tuple[str, ...] = ()
    artifacts: tuple[str, ...] = ()
    entrypoint: str | None = None
    args: tuple[str, ...] = ()
    cwd: str = "."
    capabilities: frozenset[Capability] = frozenset()
    timeout_seconds: int = Field(default=300, ge=1, le=7200)
    depends_on: tuple[str, ...] = ()
    include_in_full: bool = False
    include_in_nightly: bool = False
    required: bool = True

    @field_validator("targets", "artifacts", mode="before")
    @classmethod
    def validate_repository_paths(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("repository paths must be a list or tuple")
        return tuple(_validate_relative_posix(str(item)) for item in value)

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str | None) -> str | None:
        return _validate_relative_posix(value) if value else None

    @field_validator("cwd")
    @classmethod
    def validate_cwd(cls, value: str) -> str:
        return "." if value == "." else _validate_relative_posix(value)

    @model_validator(mode="after")
    def validate_runner_payload(self) -> VerificationGroup:
        if self.runner is Runner.PYTHON and not self.entrypoint:
            raise ValueError("python runner requires entrypoint")
        if self.runner in {Runner.RUFF, Runner.MYPY, Runner.PYTEST} and not self.targets:
            raise ValueError(f"{self.runner.value} runner requires targets")
        return self


class Component(FrozenModel):
    domain: Domain
    paths: tuple[str, ...] = Field(min_length=1)
    direct_groups: tuple[str, ...] = Field(min_length=1)
    impacts: tuple[str, ...] = ()
    risk: Risk = Risk.NORMAL

    @field_validator("paths", mode="before")
    @classmethod
    def validate_paths(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("paths must be a list or tuple")
        return tuple(_validate_relative_posix(str(item)) for item in value)


class Fallbacks(FrozenModel):
    backend: tuple[str, ...] = Field(min_length=1)
    frontend: tuple[str, ...] = Field(min_length=1)
    repository: tuple[str, ...] = Field(min_length=1)

    def for_domain(self, domain: Domain) -> tuple[str, ...]:
        return getattr(self, domain.value)


class Catalog(FrozenModel):
    schema_version: Literal[1]
    groups: dict[str, VerificationGroup] = Field(min_length=1)
    components: dict[str, Component] = Field(min_length=1)
    fallbacks: Fallbacks
    quick_groups: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> Catalog:
        safe_id = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
        for kind, identifiers in (
            ("group", self.groups),
            ("component", self.components),
        ):
            for identifier in identifiers:
                if safe_id.fullmatch(identifier) is None:
                    raise ValueError(
                        f"{kind} ID {identifier!r} must use safe kebab-case"
                    )

        group_ids = set(self.groups)
        component_ids = set(self.components)

        for component_id, component in self.components.items():
            for group_id in component.direct_groups:
                if group_id not in group_ids:
                    raise ValueError(
                        f"component {component_id!r} references unknown group {group_id!r}"
                    )
            for impacted_id in component.impacts:
                if impacted_id not in component_ids:
                    raise ValueError(
                        f"component {component_id!r} impacts unknown component {impacted_id!r}"
                    )

        for group_id, group in self.groups.items():
            for dependency_id in group.depends_on:
                if dependency_id not in group_ids:
                    raise ValueError(
                        f"group {group_id!r} depends on unknown group {dependency_id!r}"
                    )

        for domain in Domain:
            for group_id in self.fallbacks.for_domain(domain):
                if group_id not in group_ids:
                    raise ValueError(
                        f"fallback {domain.value!r} references unknown group {group_id!r}"
                    )

        for group_id in self.quick_groups:
            if group_id not in group_ids:
                raise ValueError(
                    f"quick policy references unknown group {group_id!r}"
                )
            if self.groups[group_id].kind is not VerificationKind.SMOKE:
                raise ValueError(
                    f"quick policy group {group_id!r} must use kind 'smoke'"
                )
            if not self.groups[group_id].required:
                raise ValueError(
                    f"quick policy group {group_id!r} must be required"
                )

        self._validate_execution_graph()
        return self

    def _validate_execution_graph(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(group_id: str, path: tuple[str, ...]) -> None:
            if group_id in visiting:
                cycle = " -> ".join((*path, group_id))
                raise ValueError(f"execution dependency cycle: {cycle}")
            if group_id in visited:
                return
            visiting.add(group_id)
            for dependency_id in self.groups[group_id].depends_on:
                visit(dependency_id, (*path, group_id))
            visiting.remove(group_id)
            visited.add(group_id)

        for group_id in self.groups:
            visit(group_id, ())


class PlannedGroup(FrozenModel):
    id: str
    domain: Domain
    kind: VerificationKind
    runner: Runner
    isolation: Isolation
    capabilities: frozenset[Capability]
    depends_on: tuple[str, ...]
    artifacts: tuple[str, ...]
    required: bool
    reasons: tuple[str, ...]


class VerificationPlan(FrozenModel):
    schema_version: Literal[1] = 1
    tier: Tier
    source: Literal["paths", "worktree", "range"]
    base_sha: str | None = None
    head_sha: str | None = None
    changes: tuple[Change, ...]
    groups: tuple[PlannedGroup, ...]
    required_capabilities: frozenset[Capability]
    fallbacks: tuple[str, ...] = ()
    manifest_hash: str
    plan_hash: str


class VerificationResult(FrozenModel):
    schema_version: Literal[1] = 1
    group_id: str
    required: bool
    status: ResultStatus
    exit_code: int | None
    duration_seconds: float = Field(ge=0)
    failure_kind: str | None = None
    artifacts: tuple[str, ...] = ()
    plan_hash: str
    manifest_hash: str
    output: str = ""
    remediation: str = ""


class AggregateSummary(FrozenModel):
    schema_version: Literal[1] = 1
    status: AggregateStatus
    plan_hash: str
    manifest_hash: str
    missing_groups: tuple[str, ...] = ()
    failed_groups: tuple[str, ...] = ()
    blocked_groups: tuple[str, ...] = ()
    cancelled_groups: tuple[str, ...] = ()
    unexpected_groups: tuple[str, ...] = ()
