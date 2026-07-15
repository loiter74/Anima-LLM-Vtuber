from __future__ import annotations

import fnmatch
import hashlib
import json
from pathlib import PurePosixPath

from .fingerprint import FingerprintContext, fingerprint_patterns
from .models import (
    Catalog,
    Change,
    ChangeSet,
    DockerBuildAction,
    FrozenModel,
    Runner,
    Tier,
)


class SelectedDockerScope(FrozenModel):
    scope_id: str
    reasons: tuple[str, ...]


def _matches(path: str, pattern: str) -> bool:
    normalized = path.replace("\\", "/")
    if not any(marker in pattern for marker in "*?["):
        return normalized == pattern or normalized.startswith(pattern.rstrip("/") + "/")
    path_object = PurePosixPath(normalized)
    return path_object.match(pattern) or fnmatch.fnmatchcase(normalized, pattern)


def _change_paths(change: Change) -> tuple[str, ...]:
    return (change.path,) if change.old_path is None else (change.path, change.old_path)


def select_docker_scopes(
    catalog: Catalog,
    change_set: ChangeSet,
    tier: Tier | str,
) -> tuple[SelectedDockerScope, ...]:
    selected_tier = Tier(tier)
    reasons: dict[str, set[str]] = {}
    if selected_tier in {Tier.FULL, Tier.NIGHTLY}:
        for scope_id in catalog.docker_scopes:
            reasons.setdefault(scope_id, set()).add(
                f"selected by {selected_tier.value} cold-build policy"
            )
    else:
        for change in change_set.changes:
            for path in _change_paths(change):
                matched_scopes = {
                    scope_id
                    for scope_id, scope in catalog.docker_scopes.items()
                    if any(_matches(path, pattern) for pattern in scope.paths)
                }
                for scope_id in matched_scopes:
                    reasons.setdefault(scope_id, set()).add(f"Docker input changed: {path}")
                watched = any(_matches(path, pattern) for pattern in catalog.docker_watch_paths)
                if watched and not matched_scopes:
                    for scope_id in catalog.docker_scopes:
                        reasons.setdefault(scope_id, set()).add(
                            f"unknown Docker input changed: {path}"
                        )
    return tuple(
        SelectedDockerScope(
            scope_id=scope_id,
            reasons=tuple(sorted(scope_reasons)),
        )
        for scope_id, scope_reasons in sorted(reasons.items())
    )


def plan_docker_actions(
    catalog: Catalog,
    change_set: ChangeSet,
    tier: Tier | str,
    context: FingerprintContext,
) -> tuple[DockerBuildAction, ...]:
    actions: list[DockerBuildAction] = []
    for selected in select_docker_scopes(catalog, change_set, tier):
        scope = catalog.docker_scopes[selected.scope_id]
        files = fingerprint_patterns(context.root, scope.paths, context=context)
        toolchain = context.toolchain_identity(Runner.DOCKER)
        payload = {
            "schema_version": 1,
            "scope_id": selected.scope_id,
            "service": scope.service,
            "file_digest": files.digest,
            "toolchain_identity": toolchain,
        }
        fingerprint = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        actions.append(
            DockerBuildAction(
                scope_id=selected.scope_id,
                service=scope.service,
                input_fingerprint=fingerprint,
                input_file_count=files.file_count,
                input_patterns=scope.paths,
                reasons=selected.reasons,
            )
        )
    return tuple(actions)


def fingerprint_docker_scopes(
    catalog: Catalog,
    context: FingerprintContext,
) -> dict[str, str]:
    toolchain = context.toolchain_identity(Runner.DOCKER)
    fingerprints: dict[str, str] = {}
    for scope_id, scope in sorted(catalog.docker_scopes.items()):
        files = fingerprint_patterns(context.root, scope.paths, context=context)
        payload = {
            "schema_version": 1,
            "scope_id": scope_id,
            "service": scope.service,
            "file_digest": files.digest,
            "toolchain_identity": toolchain,
        }
        fingerprints[scope_id] = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    return fingerprints


def compose_identity(catalog: Catalog, context: FingerprintContext) -> str:
    patterns = tuple(
        sorted(
            {
                pattern
                for pattern in catalog.docker_watch_paths
                if pattern == ".dockerignore" or pattern.startswith("docker-compose")
            }
        )
    )
    files = fingerprint_patterns(context.root, patterns, context=context)
    return files.digest
