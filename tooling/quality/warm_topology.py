from __future__ import annotations

import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import FrozenModel

_BUILD_LABEL = "org.animetta.build-fingerprint"
_FRESH_EVIDENCE = (
    "health",
    "readiness",
    "bounded-logs",
    "fault-recovery",
    "browser",
)


class TopologyServiceStamp(FrozenModel):
    service: str
    build_fingerprint: str
    image_id: str
    container_id: str
    started_at: str
    restart_count: int = Field(ge=0)
    oom_killed: bool
    environment_identity: str


class ObservedService(TopologyServiceStamp):
    pass


class RuntimeReadinessObservation(FrozenModel):
    status_code: int = Field(ge=100, le=599)
    ready: bool
    effective_hash: str
    semantic_hash: str


class WarmTopologyStamp(FrozenModel):
    schema_version: Literal[1] = 1
    compose_identity: str
    effective_hash: str
    semantic_hash: str
    services: dict[str, TopologyServiceStamp]


class WarmPreflightDecision(FrozenModel):
    reusable: bool
    action: Literal["reuse", "restart", "rebuild", "blocked"]
    mismatches: tuple[str, ...]
    fresh_evidence_required: tuple[str, ...] = _FRESH_EVIDENCE


class TopologyCollectionError(RuntimeError):
    pass


def environment_identity(
    environment: Iterable[str] | Mapping[str, object],
    *,
    allowed_names: Iterable[str],
) -> str:
    values: dict[str, str] = {}
    if isinstance(environment, Mapping):
        values = {str(name): str(value) for name, value in environment.items()}
    else:
        for item in environment:
            if "=" not in item:
                values[item.strip()] = ""
                continue
            name, value = item.split("=", 1)
            values[name.strip()] = value
    normalized = [
        {
            "name": name,
            "present": name in values,
            "value": values.get(name, ""),
        }
        for name in sorted(set(allowed_names))
    ]
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def collect_service_observations(
    services: Iterable[str],
    *,
    environment_allowlists: Mapping[str, tuple[str, ...]],
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    docker_executable: str = "docker",
) -> dict[str, ObservedService]:
    observations: dict[str, ObservedService] = {}
    for service in sorted(set(services)):
        allowed_names = environment_allowlists.get(service)
        if not allowed_names:
            raise TopologyCollectionError(f"environment allowlist unavailable: {service}")
        ps = command_runner(
            [docker_executable, "compose", "ps", "-q", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        container_id = ps.stdout.strip()
        if ps.returncode != 0 or not container_id:
            raise TopologyCollectionError(f"service container unavailable: {service}")
        inspected = command_runner(
            [docker_executable, "inspect", container_id],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if inspected.returncode != 0:
            raise TopologyCollectionError(f"container inspect failed: {service}")
        try:
            payload = json.loads(inspected.stdout)
            current = payload[0]
            config = current["Config"]
            state = current["State"]
        except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
            raise TopologyCollectionError(
                f"container inspect returned invalid data: {service}"
            ) from exc
        labels = config.get("Labels") or {}
        observations[service] = ObservedService(
            service=service,
            build_fingerprint=str(labels.get(_BUILD_LABEL, "")),
            image_id=str(current.get("Image", "")),
            container_id=str(current.get("Id", container_id)),
            started_at=str(state.get("StartedAt", "")),
            restart_count=int(current.get("RestartCount", 0)),
            oom_killed=bool(state.get("OOMKilled", False)),
            environment_identity=environment_identity(
                config.get("Env") or [],
                allowed_names=allowed_names,
            ),
        )
    return observations


def collect_desired_environment_identities(
    services: Iterable[str],
    *,
    environment_allowlists: Mapping[str, tuple[str, ...]],
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    docker_executable: str = "docker",
) -> dict[str, str]:
    completed = command_runner(
        [docker_executable, "compose", "config", "--format", "json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise TopologyCollectionError("current Compose configuration is unavailable")
    try:
        payload = json.loads(completed.stdout)
        configured_services = payload["services"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise TopologyCollectionError("current Compose configuration is invalid") from exc

    identities: dict[str, str] = {}
    for service in sorted(set(services)):
        allowed_names = environment_allowlists.get(service)
        if not allowed_names:
            raise TopologyCollectionError(f"environment allowlist unavailable: {service}")
        try:
            environment = configured_services[service].get("environment") or {}
        except (AttributeError, KeyError, TypeError) as exc:
            raise TopologyCollectionError(
                f"service missing from current Compose configuration: {service}"
            ) from exc
        identities[service] = environment_identity(
            environment,
            allowed_names=allowed_names,
        )
    return identities


def evaluate_warm_topology(
    stamp: WarmTopologyStamp | None,
    *,
    current_build_fingerprints: Mapping[str, str],
    current_compose_identity: str,
    desired_environment_identities: Mapping[str, str],
    observed_services: Mapping[str, ObservedService],
    readiness: RuntimeReadinessObservation,
) -> WarmPreflightDecision:
    if stamp is None:
        return WarmPreflightDecision(
            reusable=False,
            action="rebuild",
            mismatches=("topology-stamp:missing",),
        )

    mismatches: list[str] = []
    rebuild = False
    restart = False
    blocked = False
    expected_names = set(stamp.services)
    current_names = set(observed_services)
    build_names = set(current_build_fingerprints)
    desired_names = set(desired_environment_identities)
    if (
        expected_names != current_names
        or expected_names != build_names
        or expected_names != desired_names
    ):
        mismatches.append(
            "service-set:mismatch "
            f"stamp={sorted(expected_names)} observed={sorted(current_names)} "
            f"builds={sorted(build_names)} desired={sorted(desired_names)}"
        )
        rebuild = True

    if stamp.compose_identity != current_compose_identity:
        mismatches.append("compose-identity:mismatch")
        rebuild = True

    for name in sorted(expected_names & current_names & build_names & desired_names):
        expected = stamp.services[name]
        observed = observed_services[name]
        current_build = current_build_fingerprints[name]
        if expected.service != name or observed.service != name:
            mismatches.append(f"{name}:service-name:mismatch")
            rebuild = True
        if (
            expected.build_fingerprint != current_build
            or observed.build_fingerprint != current_build
        ):
            mismatches.append(f"{name}:build-fingerprint:mismatch")
            rebuild = True
        if observed.image_id != expected.image_id:
            mismatches.append(f"{name}:image-id:mismatch")
            rebuild = True
        if observed.container_id != expected.container_id:
            mismatches.append(f"{name}:container-id:mismatch")
            restart = True
        if observed.started_at != expected.started_at:
            mismatches.append(f"{name}:started-at:mismatch")
            restart = True
        if observed.restart_count != expected.restart_count:
            mismatches.append(f"{name}:restart-count:mismatch")
            restart = True
        if observed.oom_killed != expected.oom_killed or observed.oom_killed:
            mismatches.append(f"{name}:oom-killed:mismatch")
            blocked = True
        if observed.environment_identity != expected.environment_identity:
            mismatches.append(f"{name}:environment-identity:mismatch")
            restart = True
        if observed.environment_identity != desired_environment_identities[name]:
            mismatches.append(f"{name}:desired-environment-identity:mismatch")
            restart = True

    if readiness.effective_hash != stamp.effective_hash:
        mismatches.append("effective-hash:mismatch")
        restart = True
    if readiness.semantic_hash != stamp.semantic_hash:
        mismatches.append("semantic-hash:mismatch")
        restart = True
    if readiness.status_code != 200 or not readiness.ready:
        mismatches.append("current-readiness:not-ready")
        blocked = True

    if not mismatches:
        return WarmPreflightDecision(
            reusable=True,
            action="reuse",
            mismatches=(),
        )
    if rebuild:
        action: Literal["restart", "rebuild", "blocked"] = "rebuild"
    elif restart:
        action = "restart"
    elif blocked:
        action = "blocked"
    else:  # pragma: no cover - all mismatches are classified above
        action = "blocked"
    return WarmPreflightDecision(
        reusable=False,
        action=action,
        mismatches=tuple(mismatches),
    )


def probe_runtime_readiness(
    url: str,
    *,
    timeout_seconds: float = 10,
) -> RuntimeReadinessObservation:
    status_code = 503
    body = b"{}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            status_code = int(response.status)
            body = response.read()
    except urllib.error.HTTPError as exc:
        status_code = int(exc.code)
        body = exc.read()
    except (OSError, urllib.error.URLError):
        return RuntimeReadinessObservation(
            status_code=503,
            ready=False,
            effective_hash="",
            semantic_hash="",
        )
    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    return RuntimeReadinessObservation(
        status_code=status_code,
        ready=bool(payload.get("ready", False)),
        effective_hash=str(payload.get("effective_hash", "")),
        semantic_hash=str(payload.get("semantic_hash", "")),
    )


def create_warm_topology_stamp(
    *,
    current_build_fingerprints: Mapping[str, str],
    compose_identity: str,
    desired_environment_identities: Mapping[str, str],
    observed_services: Mapping[str, ObservedService],
    readiness: RuntimeReadinessObservation,
) -> WarmTopologyStamp:
    if readiness.status_code != 200 or not readiness.ready:
        raise ValueError("cannot stamp a topology that is not currently ready")
    if set(current_build_fingerprints) != set(observed_services) or set(
        current_build_fingerprints
    ) != set(desired_environment_identities):
        raise ValueError("topology stamp service set does not match build fingerprints")
    services: dict[str, TopologyServiceStamp] = {}
    for service, fingerprint in sorted(current_build_fingerprints.items()):
        observed = observed_services[service]
        if observed.build_fingerprint != fingerprint:
            raise ValueError(
                f"container build fingerprint does not match current inputs: {service}"
            )
        if observed.oom_killed or observed.restart_count != 0:
            raise ValueError(f"cannot stamp unhealthy container lifecycle: {service}")
        if observed.environment_identity != desired_environment_identities[service]:
            raise ValueError(
                f"container environment does not match current Compose configuration: {service}"
            )
        services[service] = TopologyServiceStamp.model_validate(observed.model_dump(mode="json"))
    return WarmTopologyStamp(
        compose_identity=compose_identity,
        effective_hash=readiness.effective_hash,
        semantic_hash=readiness.semantic_hash,
        services=services,
    )


def load_warm_topology_stamp(path: str | Path) -> WarmTopologyStamp | None:
    source = Path(path)
    if not source.is_file():
        return None
    return WarmTopologyStamp.model_validate_json(source.read_text(encoding="utf-8"))


def write_warm_topology_stamp(stamp: WarmTopologyStamp, path: str | Path) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(stamp.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
