from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import ValidationError

from .models import (
    Capability,
    ExecutionMode,
    FrozenModel,
    Isolation,
    PlannedGroup,
    ResultStatus,
    Runner,
    TrustScope,
    VerificationResult,
)

CACHE_SCHEMA_VERSION = 1
_LIVE_CAPABILITIES = frozenset(
    {
        Capability.BROWSER,
        Capability.DOCKER,
        Capability.NETWORK,
        Capability.GPU,
    }
)


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _filesystem_path(path: Path) -> Path:
    """Return an extended Windows path so deep cached artifacts remain addressable."""
    if os.name != "nt":
        return path
    value = str(path.resolve())
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def _safe_relative(path: str) -> PurePosixPath:
    normalized = path.replace("\\", "/").strip()
    candidate = PurePosixPath(normalized)
    if not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"cache path must be repository-relative: {path!r}")
    return candidate


def _artifact_store_failure_reason(error: OSError) -> str:
    parts = ["artifact-store-failed", type(error).__name__]
    if error.errno is not None:
        parts.append(f"errno={error.errno}")
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        parts.append(f"winerror={winerror}")
    return ":".join(parts)


class CachedArtifact(FrozenModel):
    path: str
    kind: Literal["file", "directory"]
    digest: str
    storage_path: str
    size: int


class CacheRecord(FrozenModel):
    schema_version: Literal[1] = 1
    key: str
    repository_identity: str
    trust_scope: TrustScope
    group_id: str
    input_fingerprint: str
    manifest_hash: str
    toolchain_identity: dict[str, str]
    original_plan_hash: str
    original_result_hash: str
    created_at: str
    artifacts: tuple[CachedArtifact, ...]


class CacheWriteDecision(FrozenModel):
    stored: bool
    reason: str
    key: str
    record_path: Path


class CacheLookup(FrozenModel):
    hit: bool
    reason: str
    key: str
    result: VerificationResult | None = None


def repository_identity(repository_root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        remote = completed.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        remote = ""
    source = remote or repository_root.as_posix().casefold()
    return _sha256_bytes(source.encode("utf-8"))


def _artifact_payload(path: Path) -> tuple[dict[str, object], int]:
    if path.is_symlink():
        raise ValueError(f"cached artifacts must not be symlinks: {path}")
    metadata = path.lstat()
    if path.is_file():
        size = metadata.st_size
        return (
            {
                "kind": "file",
                "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
                "size": size,
                "sha256": _sha256_file(path),
            },
            size,
        )
    if not path.is_dir():
        raise ValueError(f"unsupported artifact type: {path}")
    entries: list[dict[str, object]] = []
    total_size = 0
    for candidate in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
        relative = candidate.relative_to(path).as_posix()
        if candidate.is_symlink():
            raise ValueError(f"cached artifacts must not contain symlinks: {candidate}")
        item_metadata = candidate.lstat()
        if candidate.is_dir():
            entries.append(
                {
                    "path": relative,
                    "kind": "directory",
                    "mode": f"{stat.S_IMODE(item_metadata.st_mode):04o}",
                }
            )
            continue
        if candidate.is_file():
            total_size += item_metadata.st_size
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "mode": f"{stat.S_IMODE(item_metadata.st_mode):04o}",
                    "size": item_metadata.st_size,
                    "sha256": _sha256_file(candidate),
                }
            )
    return (
        {
            "kind": "directory",
            "mode": f"{stat.S_IMODE(metadata.st_mode):04o}",
            "entries": entries,
        },
        total_size,
    )


def artifact_digest(path: Path) -> tuple[str, int, Literal["file", "directory"]]:
    payload, size = _artifact_payload(_filesystem_path(path))
    kind: Literal["file", "directory"] = "file" if payload["kind"] == "file" else "directory"
    return _sha256_bytes(_canonical_json(payload)), size, kind


class ResultCache:
    def __init__(
        self,
        cache_root: str | Path,
        repository_root: str | Path,
        *,
        repository_identity_override: str | None = None,
    ) -> None:
        self.cache_root = Path(cache_root).resolve()
        self.repository_root = Path(repository_root).resolve()
        self.repository_identity = (
            repository_identity_override
            if repository_identity_override is not None
            else repository_identity(self.repository_root)
        )
        self.cache_root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _reusable_group(group: PlannedGroup) -> bool:
        return bool(
            group.cacheable
            and group.isolation is Isolation.HERMETIC
            and group.runner not in {Runner.PLAYWRIGHT, Runner.DOCKER}
            and not (group.capabilities & _LIVE_CAPABILITIES)
        )

    def key(
        self,
        group: PlannedGroup,
        *,
        manifest_hash: str,
        trust_scope: TrustScope,
    ) -> str:
        return _sha256_bytes(
            _canonical_json(
                {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "repository_identity": self.repository_identity,
                    "trust_scope": trust_scope.value,
                    "group_id": group.id,
                    "input_fingerprint": group.input_fingerprint,
                    "manifest_hash": manifest_hash,
                    "toolchain_identity": group.toolchain_identity,
                }
            )
        )

    def record_path(
        self,
        group: PlannedGroup,
        *,
        manifest_hash: str,
        trust_scope: TrustScope,
    ) -> Path:
        key = self.key(
            group,
            manifest_hash=manifest_hash,
            trust_scope=trust_scope,
        )
        repository_namespace = _sha256_bytes(self.repository_identity.encode("utf-8"))[:12]
        return (
            self.cache_root
            / "records"
            / repository_namespace
            / trust_scope.value
            / f"{key[:32]}.json"
        )

    @contextmanager
    def _lock(self, key: str, timeout_seconds: float = 10.0) -> Iterator[None]:
        lock_path = self.cache_root / "locks" / f"{key}.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except (FileExistsError, PermissionError):
                try:
                    if time.time() - lock_path.stat().st_mtime > 60:
                        lock_path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"timed out waiting for cache lock {key}")
                time.sleep(0.01)
        try:
            os.write(descriptor, str(os.getpid()).encode("ascii"))
            yield
        finally:
            os.close(descriptor)
            lock_path.unlink(missing_ok=True)

    def _materialize_artifact(self, path: str) -> CachedArtifact:
        relative = _safe_relative(path)
        source = self.repository_root.joinpath(*relative.parts)
        if not source.exists() or source.is_symlink():
            raise FileNotFoundError(f"declared artifact is missing or unsafe: {path}")
        digest, size, kind = artifact_digest(source)
        if kind == "file":
            storage = self.cache_root / "objects" / "files" / digest
            storage.parent.mkdir(parents=True, exist_ok=True)
            if not storage.exists():
                temporary = storage.with_name(f".{storage.name}.{uuid.uuid4().hex}.tmp")
                shutil.copy2(source, temporary)
                try:
                    os.replace(temporary, storage)
                finally:
                    temporary.unlink(missing_ok=True)
        else:
            storage = self.cache_root / "objects" / "trees" / digest
            storage.parent.mkdir(parents=True, exist_ok=True)
            if not storage.exists():
                temporary = storage.with_name(f".{storage.name}.{uuid.uuid4().hex}.tmp")
                try:
                    shutil.copytree(
                        _filesystem_path(source),
                        _filesystem_path(temporary),
                    )
                    with suppress(FileExistsError):
                        os.replace(
                            _filesystem_path(temporary),
                            _filesystem_path(storage),
                        )
                finally:
                    shutil.rmtree(_filesystem_path(temporary), ignore_errors=True)
        return CachedArtifact(
            path=path,
            kind=kind,
            digest=digest,
            storage_path=storage.relative_to(self.cache_root).as_posix(),
            size=size,
        )

    def store(
        self,
        group: PlannedGroup,
        result: VerificationResult,
        trust_scope: TrustScope,
    ) -> CacheWriteDecision:
        key = self.key(
            group,
            manifest_hash=result.manifest_hash,
            trust_scope=trust_scope,
        )
        record_path = self.record_path(
            group,
            manifest_hash=result.manifest_hash,
            trust_scope=trust_scope,
        )
        if not self._reusable_group(group):
            return CacheWriteDecision(
                stored=False,
                reason="group-not-cacheable",
                key=key,
                record_path=record_path,
            )
        if result.execution_mode is not ExecutionMode.EXECUTED:
            return CacheWriteDecision(
                stored=False,
                reason="result-not-executed",
                key=key,
                record_path=record_path,
            )
        if result.status is not ResultStatus.PASSED:
            return CacheWriteDecision(
                stored=False,
                reason="result-not-reusable",
                key=key,
                record_path=record_path,
            )
        if result.input_fingerprint != group.input_fingerprint:
            return CacheWriteDecision(
                stored=False,
                reason="fingerprint-mismatch",
                key=key,
                record_path=record_path,
            )
        if set(result.artifacts) != set(group.artifacts):
            return CacheWriteDecision(
                stored=False,
                reason="missing-artifact",
                key=key,
                record_path=record_path,
            )
        with self._lock(key):
            if record_path.exists():
                return CacheWriteDecision(
                    stored=False,
                    reason="already-stored",
                    key=key,
                    record_path=record_path,
                )
            artifacts: tuple[CachedArtifact, ...] = ()
            storage_error: OSError | None = None
            for _attempt in range(2):
                try:
                    artifacts = tuple(self._materialize_artifact(path) for path in group.artifacts)
                    storage_error = None
                    break
                except (FileNotFoundError, ValueError):
                    return CacheWriteDecision(
                        stored=False,
                        reason="missing-artifact",
                        key=key,
                        record_path=record_path,
                    )
                except OSError as error:
                    storage_error = error
            if storage_error is not None:
                return CacheWriteDecision(
                    stored=False,
                    reason=_artifact_store_failure_reason(storage_error),
                    key=key,
                    record_path=record_path,
                )
            result_payload = result.model_dump(mode="json")
            record = CacheRecord(
                key=key,
                repository_identity=self.repository_identity,
                trust_scope=trust_scope,
                group_id=group.id,
                input_fingerprint=group.input_fingerprint,
                manifest_hash=result.manifest_hash,
                toolchain_identity=group.toolchain_identity,
                original_plan_hash=result.plan_hash,
                original_result_hash=_sha256_bytes(_canonical_json(result_payload)),
                created_at=datetime.now(UTC).isoformat(),
                artifacts=artifacts,
            )
            record_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = record_path.with_name(f".{uuid.uuid4().hex}.tmp")
            payload = (
                json.dumps(
                    record.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n"
            )
            try:
                with temporary.open("x", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, record_path)
            finally:
                temporary.unlink(missing_ok=True)
        return CacheWriteDecision(
            stored=True,
            reason="stored",
            key=key,
            record_path=record_path,
        )

    def _load_record(self, path: Path) -> CacheRecord | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return CacheRecord.model_validate(payload)
        except (OSError, json.JSONDecodeError, ValidationError):
            return None

    def _validate_storage(self, artifact: CachedArtifact) -> Path | None:
        relative = _safe_relative(artifact.storage_path)
        storage = self.cache_root.joinpath(*relative.parts)
        try:
            storage.relative_to(self.cache_root)
        except ValueError:
            return None
        if not storage.exists() or storage.is_symlink():
            return None
        try:
            digest, _, kind = artifact_digest(storage)
        except (OSError, ValueError):
            return None
        if digest != artifact.digest or kind != artifact.kind:
            return None
        return storage

    def _restore_artifact(self, artifact: CachedArtifact, storage: Path) -> None:
        relative = _safe_relative(artifact.path)
        destination = self.repository_root.joinpath(*relative.parts)
        try:
            destination.relative_to(self.repository_root)
        except ValueError as exc:  # pragma: no cover - guarded by _safe_relative
            raise ValueError("artifact destination escapes repository") from exc
        if destination.exists() and not destination.is_symlink():
            try:
                current_digest, _, current_kind = artifact_digest(destination)
                if current_digest == artifact.digest and current_kind == artifact.kind:
                    return
            except (OSError, ValueError):
                pass
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        if artifact.kind == "file":
            shutil.copy2(_filesystem_path(storage), _filesystem_path(temporary))
        else:
            shutil.copytree(_filesystem_path(storage), _filesystem_path(temporary))
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.is_dir():
            shutil.rmtree(destination)
        os.replace(_filesystem_path(temporary), _filesystem_path(destination))

    def lookup(
        self,
        group: PlannedGroup,
        *,
        plan_hash: str,
        manifest_hash: str,
        trust_scope: TrustScope,
    ) -> CacheLookup:
        started = time.perf_counter()
        key = self.key(
            group,
            manifest_hash=manifest_hash,
            trust_scope=trust_scope,
        )
        if not self._reusable_group(group):
            return CacheLookup(
                hit=False,
                reason="group-not-cacheable",
                key=key,
            )
        path = self.record_path(
            group,
            manifest_hash=manifest_hash,
            trust_scope=trust_scope,
        )
        if not path.is_file():
            return CacheLookup(hit=False, reason="not-found", key=key)
        record = self._load_record(path)
        if record is None:
            return CacheLookup(hit=False, reason="corrupt-record", key=key)
        if (
            record.key != key
            or record.repository_identity != self.repository_identity
            or record.trust_scope is not trust_scope
            or record.group_id != group.id
            or record.input_fingerprint != group.input_fingerprint
            or record.manifest_hash != manifest_hash
            or record.toolchain_identity != group.toolchain_identity
        ):
            return CacheLookup(
                hit=False,
                reason="record-identity-mismatch",
                key=key,
            )
        expected_artifacts = set(group.artifacts)
        if {artifact.path for artifact in record.artifacts} != expected_artifacts:
            return CacheLookup(
                hit=False,
                reason="artifact-set-mismatch",
                key=key,
            )
        storage_by_path: dict[str, tuple[CachedArtifact, Path]] = {}
        for artifact in record.artifacts:
            storage = self._validate_storage(artifact)
            if storage is None:
                return CacheLookup(
                    hit=False,
                    reason="artifact-digest-mismatch",
                    key=key,
                )
            storage_by_path[artifact.path] = (artifact, storage)
        try:
            for artifact, storage in storage_by_path.values():
                self._restore_artifact(artifact, storage)
        except (OSError, ValueError):
            return CacheLookup(
                hit=False,
                reason="artifact-restore-failed",
                key=key,
            )
        elapsed = time.perf_counter() - started
        artifacts = tuple(sorted(storage_by_path))
        result = VerificationResult(
            group_id=group.id,
            required=group.required,
            status=ResultStatus.PASSED,
            exit_code=0,
            duration_seconds=elapsed,
            artifacts=artifacts,
            plan_hash=plan_hash,
            manifest_hash=manifest_hash,
            execution_mode=ExecutionMode.CACHE_HIT,
            input_fingerprint=group.input_fingerprint,
            trust_scope=trust_scope,
            cache_reason="exact-content-hit",
            cache_source=key,
            cache_seconds=elapsed,
            artifact_digests={
                path: artifact.digest for path, (artifact, _) in sorted(storage_by_path.items())
            },
            output=f"Reused exact hermetic result from cache record {key}",
        )
        return CacheLookup(
            hit=True,
            reason="exact-content-hit",
            key=key,
            result=result,
        )
