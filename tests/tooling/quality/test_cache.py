from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from tooling.quality.cache import ResultCache
from tooling.quality.models import (
    Capability,
    Domain,
    ExecutionMode,
    Isolation,
    PlannedGroup,
    ResourceClass,
    ResultStatus,
    Runner,
    TrustScope,
    VerificationKind,
    VerificationResult,
)


def _planned_group(
    *,
    fingerprint: str | None = "a" * 64,
    toolchain: str = "toolchain-v1",
    runner: Runner = Runner.PYTEST,
    isolation: Isolation = Isolation.HERMETIC,
    capabilities: frozenset[Capability] = frozenset(),
    artifacts: tuple[str, ...] = ("coverage.xml",),
    cacheable: bool = True,
) -> PlannedGroup:
    return PlannedGroup(
        id="backend-unit",
        domain=Domain.BACKEND,
        kind=VerificationKind.UNIT,
        runner=runner,
        isolation=isolation,
        capabilities=capabilities,
        depends_on=(),
        artifacts=artifacts,
        required=True,
        reasons=("test",),
        cacheable=cacheable,
        resource_class=ResourceClass.CPU,
        resource_weight=1,
        input_fingerprint=fingerprint,
        input_file_count=1,
        input_patterns=("src/**",),
        toolchain_identity={"identity": toolchain},
    )


def _result(
    *,
    status: ResultStatus = ResultStatus.PASSED,
    fingerprint: str = "a" * 64,
    execution_mode: ExecutionMode = ExecutionMode.EXECUTED,
    artifacts: tuple[str, ...] = ("coverage.xml",),
) -> VerificationResult:
    return VerificationResult(
        group_id="backend-unit",
        required=True,
        status=status,
        exit_code=0 if status is ResultStatus.PASSED else 1,
        duration_seconds=1.25,
        run_seconds=1.25,
        execution_mode=execution_mode,
        input_fingerprint=fingerprint,
        artifacts=artifacts,
        plan_hash="p" * 64,
        manifest_hash="m" * 64,
    )


def _cache(tmp_path: Path, repository: str = "repo-v1") -> ResultCache:
    root = tmp_path / repository
    root.mkdir(exist_ok=True)
    return ResultCache(
        tmp_path / "cache",
        root,
        repository_identity_override=repository,
    )


def _write_artifact(cache: ResultCache, content: str = "coverage") -> None:
    (cache.repository_root / "coverage.xml").write_text(content, encoding="utf-8")


def test_exact_successful_cache_hit_restores_artifact_and_emits_current_result(
    tmp_path: Path,
) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)
    written = cache.store(group, _result(), TrustScope.LOCAL)
    assert written.stored is True

    (cache.repository_root / "coverage.xml").unlink()
    lookup = cache.lookup(
        group,
        plan_hash="current-plan",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )

    assert lookup.hit is True
    assert lookup.reason == "exact-content-hit"
    assert lookup.result is not None
    assert lookup.result.plan_hash == "current-plan"
    assert lookup.result.execution_mode is ExecutionMode.CACHE_HIT
    assert lookup.result.cache_source == written.key
    assert (cache.repository_root / "coverage.xml").read_text(encoding="utf-8") == "coverage"


@pytest.mark.parametrize(
    ("group", "manifest_hash", "trust_scope"),
    [
        (_planned_group(fingerprint="b" * 64), "m" * 64, TrustScope.LOCAL),
        (_planned_group(toolchain="toolchain-v2"), "m" * 64, TrustScope.LOCAL),
        (_planned_group(), "n" * 64, TrustScope.LOCAL),
        (_planned_group(), "m" * 64, TrustScope.PR),
    ],
)
def test_cache_misses_on_content_toolchain_manifest_or_trust_change(
    tmp_path: Path,
    group: PlannedGroup,
    manifest_hash: str,
    trust_scope: TrustScope,
) -> None:
    cache = _cache(tmp_path)
    _write_artifact(cache)
    cache.store(_planned_group(), _result(), TrustScope.LOCAL)

    lookup = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash=manifest_hash,
        trust_scope=trust_scope,
    )

    assert lookup.hit is False
    assert lookup.result is None


def test_cache_is_namespaced_by_repository_identity(tmp_path: Path) -> None:
    first = _cache(tmp_path, "repository-one")
    _write_artifact(first)
    first.store(_planned_group(), _result(), TrustScope.LOCAL)
    second = _cache(tmp_path, "repository-two")

    lookup = second.lookup(
        _planned_group(),
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )

    assert lookup.hit is False


@pytest.mark.parametrize(
    "status",
    [
        ResultStatus.FAILED,
        ResultStatus.BLOCKED,
        ResultStatus.CANCELLED,
        ResultStatus.SKIPPED,
    ],
)
def test_non_passing_results_are_never_stored(
    tmp_path: Path,
    status: ResultStatus,
) -> None:
    cache = _cache(tmp_path)
    _write_artifact(cache)

    decision = cache.store(_planned_group(), _result(status=status), TrustScope.LOCAL)

    assert decision.stored is False
    assert decision.reason == "result-not-reusable"


@pytest.mark.parametrize(
    "group",
    [
        _planned_group(cacheable=False),
        _planned_group(isolation=Isolation.SERVICE),
        _planned_group(runner=Runner.PLAYWRIGHT),
        _planned_group(runner=Runner.DOCKER),
        _planned_group(capabilities=frozenset({Capability.NETWORK})),
        _planned_group(capabilities=frozenset({Capability.GPU})),
        _planned_group(capabilities=frozenset({Capability.BROWSER})),
        _planned_group(capabilities=frozenset({Capability.DOCKER})),
    ],
)
def test_non_hermetic_or_live_groups_are_never_stored(
    tmp_path: Path,
    group: PlannedGroup,
) -> None:
    cache = _cache(tmp_path)
    _write_artifact(cache)

    decision = cache.store(group, _result(), TrustScope.LOCAL)

    assert decision.stored is False
    assert decision.reason == "group-not-cacheable"


def test_cache_hit_result_is_not_reinserted(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    _write_artifact(cache)

    decision = cache.store(
        _planned_group(),
        _result(execution_mode=ExecutionMode.CACHE_HIT),
        TrustScope.LOCAL,
    )

    assert decision.stored is False
    assert decision.reason == "result-not-executed"


def test_result_without_bound_input_fingerprint_is_never_stored(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    _write_artifact(cache)

    decision = cache.store(
        _planned_group(),
        _result(fingerprint=None),
        TrustScope.LOCAL,
    )

    assert decision.stored is False
    assert decision.reason == "fingerprint-mismatch"


@pytest.mark.parametrize("damage", ["missing", "mutated"])
def test_missing_or_mutated_cached_artifact_forces_miss(
    tmp_path: Path,
    damage: str,
) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)
    written = cache.store(group, _result(), TrustScope.LOCAL)
    record = json.loads(written.record_path.read_text(encoding="utf-8"))
    stored_artifact = cache.cache_root / record["artifacts"][0]["storage_path"]
    if damage == "missing":
        stored_artifact.unlink()
    else:
        stored_artifact.write_text("poisoned", encoding="utf-8")

    lookup = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )

    assert lookup.hit is False
    assert "artifact" in lookup.reason


def test_corrupt_partial_or_cross_trust_record_cannot_hit(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)
    written = cache.store(group, _result(), TrustScope.LOCAL)

    local_record = written.record_path
    pr_record = cache.record_path(
        group,
        manifest_hash="m" * 64,
        trust_scope=TrustScope.PR,
    )
    pr_record.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_record, pr_record)
    poisoned = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.PR,
    )
    assert poisoned.hit is False
    assert poisoned.reason == "record-identity-mismatch"

    local_record.write_text("{not-json", encoding="utf-8")
    corrupt = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )
    assert corrupt.hit is False
    assert corrupt.reason == "corrupt-record"

    local_record.unlink()
    local_record.with_suffix(".json.interrupted.tmp").write_text("{}", encoding="utf-8")
    partial = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )
    assert partial.hit is False
    assert partial.reason == "not-found"


def test_concurrent_writers_publish_one_valid_record(tmp_path: Path) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)

    with ThreadPoolExecutor(max_workers=8) as pool:
        decisions = list(
            pool.map(
                lambda _: cache.store(group, _result(), TrustScope.LOCAL),
                range(16),
            )
        )

    assert all(decision.stored or decision.reason == "already-stored" for decision in decisions)
    assert sum(decision.stored for decision in decisions) == 1
    lookup = cache.lookup(
        group,
        plan_hash="current",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )
    assert lookup.hit is True


def test_directory_artifact_round_trip_supports_long_windows_paths(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / ("cache-" + "c" * 48)
    repository_root = tmp_path / "repo"
    artifact_path = "frontend/dist"
    long_asset_name = "ProcessTimeline.vue_vue_type_script_setup_true_lang-Ci08vcxR.js"
    asset = repository_root / artifact_path / "assets" / long_asset_name
    asset.parent.mkdir(parents=True)
    asset.write_text("export const built = true\n", encoding="utf-8")
    cache = ResultCache(
        cache_root,
        repository_root,
        repository_identity_override="repo-long-path",
    )
    group = _planned_group(artifacts=(artifact_path,))
    result = _result(artifacts=(artifact_path,))

    written = cache.store(group, result, TrustScope.LOCAL)
    assert written.stored is True

    shutil.rmtree(repository_root / artifact_path)
    lookup = cache.lookup(
        group,
        plan_hash="current-plan",
        manifest_hash="m" * 64,
        trust_scope=TrustScope.LOCAL,
    )

    assert lookup.hit is True
    assert asset.read_text(encoding="utf-8") == "export const built = true\n"


def test_artifact_storage_io_error_does_not_turn_passing_result_into_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)

    def fail_materialization(path: str):
        raise OSError(f"cannot materialize {path}")

    monkeypatch.setattr(cache, "_materialize_artifact", fail_materialization)

    decision = cache.store(group, _result(), TrustScope.LOCAL)

    assert decision.stored is False
    assert decision.reason == "artifact-store-failed:OSError"


def test_transient_artifact_storage_io_error_is_retried_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = _cache(tmp_path)
    group = _planned_group()
    _write_artifact(cache)
    materialize = cache._materialize_artifact
    attempts = 0

    def transient_failure(path: str):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("transient cache storage failure")
        return materialize(path)

    monkeypatch.setattr(cache, "_materialize_artifact", transient_failure)

    decision = cache.store(group, _result(), TrustScope.LOCAL)

    assert decision.stored is True
    assert decision.reason == "stored"
    assert attempts == 2
