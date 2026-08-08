from __future__ import annotations

import json
import subprocess

import pytest
from pydantic import ValidationError

from tooling.quality.warm_topology import (
    ObservedService,
    RuntimeReadinessObservation,
    TopologyServiceStamp,
    WarmTopologyStamp,
    collect_desired_environment_identities,
    collect_service_observations,
    environment_identity,
    evaluate_warm_topology,
)


def _service(name: str, fingerprint: str) -> TopologyServiceStamp:
    return TopologyServiceStamp(
        service=name,
        build_fingerprint=fingerprint,
        image_id=f"sha256:{name}-image",
        container_id=f"{name}-container",
        started_at="2026-07-15T00:00:00Z",
        restart_count=0,
        oom_killed=False,
        environment_identity=f"{name}-environment",
    )


def _observed(stamp: TopologyServiceStamp) -> ObservedService:
    return ObservedService(**stamp.model_dump())


def _stamp() -> WarmTopologyStamp:
    return WarmTopologyStamp(
        compose_identity="compose-v1",
        effective_hash="effective-v1",
        semantic_hash="semantic-v1",
        services={
            "animetta": _service("animetta", "core-v1"),
        },
    )


def _readiness(*, ready: bool = True) -> RuntimeReadinessObservation:
    return RuntimeReadinessObservation(
        status_code=200 if ready else 503,
        ready=ready,
        effective_hash="effective-v1",
        semantic_hash="semantic-v1",
    )


def _desired(stamp: WarmTopologyStamp) -> dict[str, str]:
    return {name: service.environment_identity for name, service in stamp.services.items()}


def _allowlists() -> dict[str, tuple[str, ...]]:
    return {
        "animetta": ("ANIMETTA_PROFILE", "DEEPSEEK_API_KEY"),
    }


def test_exact_warm_topology_match_allows_reuse_but_requires_fresh_evidence() -> None:
    stamp = _stamp()
    observed = {name: _observed(service) for name, service in stamp.services.items()}

    decision = evaluate_warm_topology(
        stamp,
        current_build_fingerprints={"animetta": "core-v1"},
        current_compose_identity="compose-v1",
        desired_environment_identities=_desired(stamp),
        observed_services=observed,
        readiness=_readiness(),
    )

    assert decision.reusable is True
    assert decision.action == "reuse"
    assert decision.mismatches == ()
    assert set(decision.fresh_evidence_required) == {
        "health",
        "readiness",
        "bounded-logs",
        "fault-recovery",
        "browser",
    }


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        ("service-set", "service-set"),
        ("current-build", "build-fingerprint"),
        ("image", "image-id"),
        ("container", "container-id"),
        ("started", "started-at"),
        ("restart", "restart-count"),
        ("oom", "oom-killed"),
        ("environment", "environment-identity"),
        ("desired-environment", "desired-environment-identity"),
        ("compose", "compose-identity"),
        ("effective", "effective-hash"),
        ("semantic", "semantic-hash"),
        ("readiness", "current-readiness"),
    ],
)
def test_every_identity_lifecycle_or_readiness_mismatch_fails_closed(
    mutation: str,
    expected_fragment: str,
) -> None:
    stamp = _stamp()
    builds = {"animetta": "core-v1"}
    compose = "compose-v1"
    readiness = _readiness()
    observed = {name: _observed(service) for name, service in stamp.services.items()}
    desired = _desired(stamp)
    if mutation == "service-set":
        observed.pop("animetta")
    elif mutation == "current-build":
        builds["animetta"] = "core-v2"
    elif mutation == "compose":
        compose = "compose-v2"
    elif mutation == "effective":
        readiness = readiness.model_copy(update={"effective_hash": "effective-v2"})
    elif mutation == "semantic":
        readiness = readiness.model_copy(update={"semantic_hash": "semantic-v2"})
    elif mutation == "readiness":
        readiness = _readiness(ready=False)
    elif mutation == "desired-environment":
        desired["animetta"] = "new-desired-environment"
    else:
        field_updates = {
            "image": {"image_id": "sha256:new-image"},
            "container": {"container_id": "new-container"},
            "started": {"started_at": "2026-07-15T01:00:00Z"},
            "restart": {"restart_count": 1},
            "oom": {"oom_killed": True},
            "environment": {"environment_identity": "changed"},
        }
        observed["animetta"] = observed["animetta"].model_copy(update=field_updates[mutation])

    decision = evaluate_warm_topology(
        stamp,
        current_build_fingerprints=builds,
        current_compose_identity=compose,
        desired_environment_identities=desired,
        observed_services=observed,
        readiness=readiness,
    )

    assert decision.reusable is False
    assert decision.action in {"rebuild", "restart", "blocked"}
    assert any(expected_fragment in mismatch for mismatch in decision.mismatches)


def test_missing_stamp_requires_rebuild() -> None:
    decision = evaluate_warm_topology(
        None,
        current_build_fingerprints={"animetta": "core-v1"},
        current_compose_identity="compose-v1",
        desired_environment_identities={"animetta": "desired"},
        observed_services={},
        readiness=_readiness(ready=False),
    )

    assert decision.reusable is False
    assert decision.action == "rebuild"
    assert decision.mismatches == ("topology-stamp:missing",)


def test_environment_identity_uses_only_declared_fields_and_redacts_values() -> None:
    allowed = ("ANIMETTA_PROFILE", "DEEPSEEK_API_KEY")
    first = environment_identity(
        [
            "ANIMETTA_PROFILE=production",
            "DEEPSEEK_API_KEY=super-secret-value",
            "PATH=first-runtime-path",
        ],
        allowed_names=allowed,
    )
    reordered = environment_identity(
        [
            "DEEPSEEK_API_KEY=super-secret-value",
            "ANIMETTA_PROFILE=production",
            "PATH=different-runtime-path",
        ],
        allowed_names=allowed,
    )
    changed = environment_identity(
        [
            "ANIMETTA_PROFILE=production",
            "DEEPSEEK_API_KEY=different-secret-value",
        ],
        allowed_names=allowed,
    )

    assert first == reordered
    assert first != changed
    assert "super-secret-value" not in first
    assert len(first) == 64


def test_collector_is_read_only_and_extracts_lifecycle_identity() -> None:
    commands: list[list[str]] = []

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        commands.append(argv)
        if "ps" in argv and "-q" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout="container-id\n", stderr="")
        inspect = [
            {
                "Id": "container-id",
                "Image": "sha256:image",
                "Config": {
                    "Env": ["ANIMETTA_PROFILE=production"],
                    "Labels": {"org.animetta.build-fingerprint": "build-v1"},
                },
                "State": {
                    "StartedAt": "2026-07-15T00:00:00Z",
                    "Restarting": False,
                    "OOMKilled": False,
                },
                "RestartCount": 0,
            }
        ]
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(inspect), stderr="")

    observed = collect_service_observations(
        ("animetta",),
        environment_allowlists={"animetta": ("ANIMETTA_PROFILE",)},
        compose_files={"animetta": "docker-compose.yml"},
        command_runner=run,
    )

    assert observed["animetta"].container_id == "container-id"
    assert observed["animetta"].build_fingerprint == "build-v1"
    assert commands[0][:5] == [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "ps",
    ]
    assert all(
        not ({"build", "up", "down", "restart", "start", "stop"} & set(command))
        for command in commands
    )


def test_desired_environment_identity_comes_from_each_scope_compose_config() -> None:
    compose_by_file = {
        "docker-compose.yml": {
            "services": {
                "animetta": {
                    "environment": {
                        "ANIMETTA_PROFILE": "production",
                        "DEEPSEEK_API_KEY": "rotated-secret",
                        "PATH": "irrelevant",
                    }
                }
            }
        },
    }

    def run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        compose_file = argv[argv.index("-f") + 1]
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(compose_by_file[compose_file]),
            stderr="",
        )

    identities = collect_desired_environment_identities(
        ("animetta",),
        environment_allowlists=_allowlists(),
        compose_files={
            "animetta": "docker-compose.yml",
        },
        command_runner=run,
    )

    assert identities["animetta"] == environment_identity(
        [
            "ANIMETTA_PROFILE=production",
            "DEEPSEEK_API_KEY=rotated-secret",
        ],
        allowed_names=_allowlists()["animetta"],
    )
    assert "rotated-secret" not in identities["animetta"]


def test_old_topology_stamp_schema_is_rejected() -> None:
    payload = _stamp().model_dump(mode="json")
    payload["schema_version"] = 0

    with pytest.raises(ValidationError, match="schema_version"):
        WarmTopologyStamp.model_validate(payload)
