from __future__ import annotations

import re
from collections.abc import Sequence
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
    RUFF_FORMAT = "ruff-format"
    MYPY = "mypy"
    VULTURE = "vulture"
    PYTEST = "pytest"
    PYTHON = "python"
    NPM = "npm"
    PNPM = "pnpm"
    VITEST = "vitest"
    PLAYWRIGHT = "playwright"
    DOCKER = "docker"


NPM_COMMAND_SEPARATOR = "::"


def parse_npm_commands(arguments: Sequence[str]) -> tuple[tuple[str, ...], ...]:
    """Split a catalog npm payload into non-empty command argv sequences."""

    if not arguments:
        raise ValueError("npm command sequence requires at least one command")

    commands: list[tuple[str, ...]] = []
    current: list[str] = []
    for argument in arguments:
        if argument == NPM_COMMAND_SEPARATOR:
            if not current:
                raise ValueError("npm command sequence contains an empty command")
            commands.append(tuple(current))
            current = []
            continue
        current.append(argument)
    if not current:
        raise ValueError("npm command sequence contains an empty command")
    commands.append(tuple(current))
    return tuple(commands)


class Isolation(StrEnum):
    HERMETIC = "hermetic"
    SERVICE = "service"
    EXTERNAL = "external"


class ResourceClass(StrEnum):
    LIGHT = "light"
    CPU = "cpu"
    HEAVY = "heavy"
    EXCLUSIVE = "exclusive"


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


class ExecutionMode(StrEnum):
    EXECUTED = "executed"
    CACHE_HIT = "cache-hit"


class TrustScope(StrEnum):
    LOCAL = "local"
    PR = "pr"
    MAIN = "main"
    RELEASE = "release"


class CacheMode(StrEnum):
    OFF = "off"
    READ = "read"
    READ_WRITE = "read-write"


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


def _validate_fingerprint_pattern(value: str) -> str:
    normalized = _validate_relative_posix(value)
    secret_names = {".env", "credentials", "secrets"}
    for part in PurePosixPath(normalized).parts:
        lowered = part.casefold()
        if lowered == ".env.example":
            continue
        if (
            lowered in secret_names
            or lowered.startswith(".env.")
            or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
        ):
            raise ValueError(f"fingerprint inputs must not include secret material: {value!r}")
    return normalized


class FingerprintInputSet(FrozenModel):
    paths: tuple[str, ...] = Field(min_length=1)

    @field_validator("paths", mode="before")
    @classmethod
    def validate_paths(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("paths must be a list or tuple")
        return tuple(_validate_fingerprint_pattern(str(item)) for item in value)


class SchedulerPolicy(FrozenModel):
    max_workers: int = Field(default=4, ge=1, le=64)
    max_weight: int = Field(default=4, ge=1, le=64)
    max_heavy: int = Field(default=1, ge=1, le=64)
    max_exclusive: int = Field(default=1, ge=1, le=64)


class DockerBuildScope(FrozenModel):
    service: str
    compose_file: str
    paths: tuple[str, ...] = Field(min_length=1)
    environment_identity_fields: tuple[str, ...] = Field(min_length=1)

    @field_validator("paths", mode="before")
    @classmethod
    def validate_paths(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)):
            raise ValueError("paths must be a list or tuple")
        return tuple(_validate_fingerprint_pattern(str(item)) for item in value)

    @field_validator("service")
    @classmethod
    def validate_service(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) is None:
            raise ValueError("service must use safe kebab-case")
        return value

    @field_validator("compose_file")
    @classmethod
    def validate_compose_file(cls, value: str) -> str:
        return _validate_relative_posix(value)

    @field_validator("environment_identity_fields", mode="before")
    @classmethod
    def validate_environment_identity_fields(cls, value: object) -> object:
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("environment_identity_fields must be a non-empty list")
        fields = tuple(str(item).strip() for item in value)
        if len(set(fields)) != len(fields):
            raise ValueError("environment_identity_fields must be unique")
        if any(re.fullmatch(r"[A-Z][A-Z0-9_]*", field) is None for field in fields):
            raise ValueError("environment identity fields must use uppercase environment names")
        return fields


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
    cacheable: bool = False
    resource_class: ResourceClass = ResourceClass.CPU
    resource_weight: int = Field(default=1, ge=1, le=64)
    input_sets: tuple[str, ...] = ()
    covers: tuple[str, ...] = ()

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
        if self.runner is Runner.NPM:
            parse_npm_commands(self.args)
        if (
            self.runner
            in {Runner.RUFF, Runner.RUFF_FORMAT, Runner.MYPY, Runner.VULTURE, Runner.PYTEST}
            and not self.targets
        ):
            raise ValueError(f"{self.runner.value} runner requires targets")
        if self.cacheable and self.isolation is not Isolation.HERMETIC:
            raise ValueError("cacheable groups must use hermetic isolation")
        if self.cacheable and (
            self.runner in {Runner.PLAYWRIGHT, Runner.DOCKER}
            or self.capabilities
            & {
                Capability.BROWSER,
                Capability.DOCKER,
                Capability.NETWORK,
                Capability.GPU,
            }
        ):
            raise ValueError(
                "cacheable groups must not require live browser, Docker, network, or GPU state"
            )
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
    input_sets: dict[str, FingerprintInputSet] = {}
    default_input_sets: tuple[str, ...] = ()
    scheduler: SchedulerPolicy = SchedulerPolicy()
    docker_watch_paths: tuple[str, ...] = ()
    docker_scopes: dict[str, DockerBuildScope] = {}

    @field_validator("docker_watch_paths", mode="before")
    @classmethod
    def validate_docker_watch_paths(cls, value: object) -> object:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("docker_watch_paths must be a list or tuple")
        return tuple(_validate_fingerprint_pattern(str(item)) for item in value)

    @model_validator(mode="after")
    def validate_references(self) -> Catalog:
        safe_id = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
        for kind, identifiers in (
            ("group", self.groups),
            ("component", self.components),
            ("input set", self.input_sets),
            ("Docker scope", self.docker_scopes),
        ):
            for identifier in identifiers:
                if safe_id.fullmatch(identifier) is None:
                    raise ValueError(f"{kind} ID {identifier!r} must use safe kebab-case")

        group_ids = set(self.groups)
        component_ids = set(self.components)
        input_set_ids = set(self.input_sets)

        for input_set_id in self.default_input_sets:
            if input_set_id not in input_set_ids:
                raise ValueError(f"default inputs reference unknown input set {input_set_id!r}")

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
            if group.resource_weight > self.scheduler.max_weight:
                raise ValueError(f"group {group_id!r} resource_weight exceeds scheduler max_weight")
            for input_set_id in group.input_sets:
                if input_set_id not in input_set_ids:
                    raise ValueError(
                        f"group {group_id!r} references unknown input set {input_set_id!r}"
                    )
            for dependency_id in group.depends_on:
                if dependency_id not in group_ids:
                    raise ValueError(
                        f"group {group_id!r} depends on unknown group {dependency_id!r}"
                    )
            for covered_id in group.covers:
                if covered_id not in group_ids:
                    raise ValueError(f"group {group_id!r} covers unknown group {covered_id!r}")
                if covered_id == group_id:
                    raise ValueError(f"group {group_id!r} cannot cover itself")

        for domain in Domain:
            for group_id in self.fallbacks.for_domain(domain):
                if group_id not in group_ids:
                    raise ValueError(
                        f"fallback {domain.value!r} references unknown group {group_id!r}"
                    )

        for group_id in self.quick_groups:
            if group_id not in group_ids:
                raise ValueError(f"quick policy references unknown group {group_id!r}")
            if self.groups[group_id].kind is not VerificationKind.SMOKE:
                raise ValueError(f"quick policy group {group_id!r} must use kind 'smoke'")
            if not self.groups[group_id].required:
                raise ValueError(f"quick policy group {group_id!r} must be required")

        self._validate_execution_graph()
        self._validate_coverage_graph()
        for group_id, group in self.groups.items():
            for covered_id in group.covers:
                self._validate_coverage(group_id, covered_id)
        return self

    def _validate_coverage(self, covering_id: str, covered_id: str) -> None:
        covering = self.groups[covering_id]
        covered = self.groups[covered_id]
        if covered.required and not covering.required:
            raise ValueError(
                f"coverage execution contract for group {covering_id!r} is weaker "
                f"than required group {covered_id!r}"
            )
        if covering.isolation is not covered.isolation:
            raise ValueError(
                f"coverage execution contract for group {covering_id!r} has incompatible "
                f"isolation for {covered_id!r}"
            )
        if not covering.capabilities.issuperset(covered.capabilities):
            raise ValueError(
                f"coverage execution contract for group {covering_id!r} lacks capabilities "
                f"required by {covered_id!r}"
            )
        if covering.runner is not covered.runner:
            raise ValueError(
                f"group {covering_id!r} must use a compatible runner to cover {covered_id!r}"
            )
        if covering.runner is not Runner.PYTEST:
            return
        covering_filters = self._pytest_selection_filters(covering.args)
        covered_filters = self._pytest_selection_filters(covered.args)
        if covering_filters and covering_filters != covered_filters:
            raise ValueError(
                f"group {covering_id!r} has selection filters that are not "
                f"a proven superset of {covered_id!r}"
            )
        for covered_target in covered.targets:
            if not any(
                covered_target == covering_target
                or covered_target.startswith(covering_target.rstrip("/") + "/")
                for covering_target in covering.targets
            ):
                raise ValueError(
                    f"group {covering_id!r} does not cover target {covered_target!r} "
                    f"from {covered_id!r}"
                )

    @staticmethod
    def _pytest_selection_filters(args: tuple[str, ...]) -> tuple[str, ...]:
        filters: list[str] = []
        value_options = {
            "-k",
            "-m",
            "--ignore",
            "--ignore-glob",
            "--deselect",
            "--lfnf",
            "--last-failed-no-failures",
        }
        flag_options = {"--lf", "--last-failed", "--ff", "--failed-first"}
        index = 0
        while index < len(args):
            argument = args[index]
            if argument in value_options:
                value = args[index + 1] if index + 1 < len(args) else ""
                filters.extend((argument, value))
                index += 2
                continue
            if (
                any(argument.startswith(option + "=") for option in value_options)
                or argument in flag_options
            ):
                filters.append(argument)
            index += 1
        return tuple(filters)

    def _validate_coverage_graph(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(group_id: str, path: tuple[str, ...]) -> None:
            if group_id in visiting:
                cycle = " -> ".join((*path, group_id))
                raise ValueError(f"coverage cycle: {cycle}")
            if group_id in visited:
                return
            visiting.add(group_id)
            for covered_id in self.groups[group_id].covers:
                visit(covered_id, (*path, group_id))
            visiting.remove(group_id)
            visited.add(group_id)

        for group_id in self.groups:
            visit(group_id, ())

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
    cacheable: bool = False
    resource_class: ResourceClass = ResourceClass.CPU
    resource_weight: int = Field(default=1, ge=1, le=64)
    fingerprint_schema_version: Literal[1] = 1
    input_fingerprint: str = "0" * 64
    input_file_count: int = Field(default=0, ge=0)
    input_patterns: tuple[str, ...] = ()
    toolchain_identity: dict[str, str] = {}


class DominatedGroup(FrozenModel):
    id: str
    covering_group: str
    reasons: tuple[str, ...]


class DockerBuildAction(FrozenModel):
    scope_id: str
    service: str
    compose_file: str
    input_fingerprint: str
    input_file_count: int = Field(ge=0)
    input_patterns: tuple[str, ...]
    reasons: tuple[str, ...]


class VerificationPlan(FrozenModel):
    schema_version: Literal[3] = 3
    fingerprint_schema_version: Literal[1] = 1
    tier: Tier
    source: Literal["paths", "worktree", "range"]
    base_sha: str | None = None
    head_sha: str | None = None
    changes: tuple[Change, ...]
    groups: tuple[PlannedGroup, ...]
    required_capabilities: frozenset[Capability]
    fallbacks: tuple[str, ...] = ()
    unmapped_paths: tuple[str, ...] = ()
    dominated_groups: tuple[DominatedGroup, ...] = ()
    docker_actions: tuple[DockerBuildAction, ...] = ()
    docker_scope_fingerprints: dict[str, str] = {}
    compose_identity: str = ""
    scheduler: SchedulerPolicy = SchedulerPolicy()
    manifest_hash: str
    plan_hash: str


class VerificationResult(FrozenModel):
    schema_version: Literal[2] = 2
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
    execution_mode: ExecutionMode = ExecutionMode.EXECUTED
    input_fingerprint: str | None = None
    trust_scope: TrustScope | None = None
    cache_reason: str = ""
    cache_source: str | None = None
    queue_seconds: float = Field(default=0, ge=0)
    run_seconds: float = Field(default=0, ge=0)
    cache_seconds: float = Field(default=0, ge=0)
    artifact_digests: dict[str, str] = {}


class AggregateSummary(FrozenModel):
    schema_version: Literal[2] = 2
    status: AggregateStatus
    plan_hash: str
    manifest_hash: str
    missing_groups: tuple[str, ...] = ()
    failed_groups: tuple[str, ...] = ()
    blocked_groups: tuple[str, ...] = ()
    cancelled_groups: tuple[str, ...] = ()
    unexpected_groups: tuple[str, ...] = ()
    dominated_groups: tuple[DominatedGroup, ...] = ()
    docker_actions: tuple[DockerBuildAction, ...] = ()
    cache_hit_groups: tuple[str, ...] = ()
    executed_groups: tuple[str, ...] = ()
    cache_miss_groups: tuple[str, ...] = ()
    wall_seconds: float = Field(default=0, ge=0)
    critical_path_seconds: float = Field(default=0, ge=0)
    planning_seconds: float = Field(default=0, ge=0)
    queue_seconds: float = Field(default=0, ge=0)
    run_seconds: float = Field(default=0, ge=0)
    cache_seconds: float = Field(default=0, ge=0)
    cache_hit_ratio: float = Field(default=0, ge=0, le=1)
