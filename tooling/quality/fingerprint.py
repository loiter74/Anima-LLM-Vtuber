from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import stat
import subprocess
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field

from .models import Catalog, Change, FrozenModel, Runner
from .path_matching import matches_repository_path

FINGERPRINT_SCHEMA_VERSION: Literal[1] = 1
_CHUNK_SIZE = 1024 * 1024
_GLOB_MARKERS = frozenset("*?[")
_SECRET_NAMES = frozenset({".env", "credentials", "secrets"})


class FileFingerprint(FrozenModel):
    path: str
    type: Literal["file", "symlink"]
    mode: str
    size: int = Field(ge=0)
    sha256: str | None = None
    link_target: str | None = None


class PatternFingerprint(FrozenModel):
    schema_version: Literal[1] = 1
    digest: str
    file_count: int = Field(ge=0)
    patterns: tuple[str, ...]
    paths: tuple[str, ...]
    entries: tuple[FileFingerprint, ...]


class GroupFingerprint(FrozenModel):
    schema_version: Literal[1] = 1
    digest: str
    file_digest: str
    file_count: int = Field(ge=0)
    patterns: tuple[str, ...]
    toolchain_identity: dict[str, str]
    dependency_fingerprints: dict[str, str]


def _canonical_json(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: object) -> str:
    return hashlib.sha256(_canonical_json(payload)).hexdigest()


def _normalize_pattern(pattern: str) -> str:
    normalized = pattern.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"fingerprint path must be repository-relative: {pattern!r}")
    for part in path.parts:
        lowered = part.casefold()
        if lowered == ".env.example":
            continue
        if (
            lowered in _SECRET_NAMES
            or lowered.startswith(".env.")
            or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
        ):
            raise ValueError(f"fingerprint inputs must not include secret material: {pattern!r}")
    return normalized


def is_safe_fingerprint_pattern(pattern: str) -> bool:
    try:
        _normalize_pattern(pattern)
    except ValueError:
        return False
    return True


def _stream_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class FingerprintContext:
    def __init__(
        self,
        repository_root: str | Path,
        *,
        toolchain_identity_override: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(repository_root).resolve()
        if not self.root.is_dir():
            raise ValueError(f"repository root does not exist: {self.root}")
        self._hash_cache: dict[tuple[str, int, int, int], str] = {}
        self._entry_cache: dict[tuple[str, int, int, int, str], FileFingerprint] = {}
        self._pattern_cache: dict[str, tuple[FileFingerprint, ...]] = {}
        self._toolchain_override = (
            dict(sorted(toolchain_identity_override.items()))
            if toolchain_identity_override is not None
            else None
        )
        self._toolchain_cache: dict[Runner, dict[str, str]] = {}
        self._git_loaded = False
        self._git_blobs: dict[str, str] = {}
        self._git_dirty: set[str] = set()
        self._git_inventory_available = False
        self._git_paths: set[str] = set()

    def _load_git_index(self) -> None:
        if self._git_loaded:
            return
        self._git_loaded = True
        if not (self.root / ".git").exists() or shutil.which("git") is None:
            return
        try:
            tracked = subprocess.run(
                ["git", "ls-files", "-s", "-z"],
                cwd=self.root,
                check=False,
                capture_output=True,
                timeout=10,
            )
            modified = subprocess.run(
                ["git", "diff-files", "--name-only", "-z"],
                cwd=self.root,
                check=False,
                capture_output=True,
                timeout=10,
            )
            untracked = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard", "-z"],
                cwd=self.root,
                check=False,
                capture_output=True,
                timeout=10,
            )
            flags = subprocess.run(
                ["git", "ls-files", "-v", "-z"],
                cwd=self.root,
                check=False,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return
        tracked_paths: set[str] = set()
        if tracked.returncode == 0:
            for raw_record in tracked.stdout.split(b"\0"):
                if not raw_record or b"\t" not in raw_record:
                    continue
                metadata, raw_path = raw_record.split(b"\t", 1)
                parts = metadata.split()
                if len(parts) < 3 or parts[2] != b"0":
                    continue
                path = raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                self._git_blobs[path] = parts[1].decode("ascii")
                tracked_paths.add(path)
        untracked_paths = {
            raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
            for raw_path in untracked.stdout.split(b"\0")
            if raw_path
        }
        if tracked.returncode == 0 and untracked.returncode == 0:
            self._git_inventory_available = True
            self._git_paths.update(tracked_paths)
            self._git_paths.update(untracked_paths)
        for completed in (modified, untracked):
            if completed.returncode != 0:
                continue
            self._git_dirty.update(
                raw_path.decode("utf-8", errors="surrogateescape").replace("\\", "/")
                for raw_path in completed.stdout.split(b"\0")
                if raw_path
            )
        if flags.returncode == 0:
            for raw_record in flags.stdout.split(b"\0"):
                if len(raw_record) < 3:
                    continue
                flag = chr(raw_record[0])
                if flag.islower() or flag == "S":
                    path = (
                        raw_record[2:].decode("utf-8", errors="surrogateescape").replace("\\", "/")
                    )
                    self._git_dirty.add(path)

    def _hash_file(self, path: Path, mode: int, size: int, mtime_ns: int) -> str:
        key = (path.as_posix(), mode, size, mtime_ns)
        cached = self._hash_cache.get(key)
        if cached is not None:
            return cached
        self._load_git_index()
        relative = path.relative_to(self.root).as_posix()
        git_blob = self._git_blobs.get(relative)
        value = (
            f"git-blob:{git_blob}"
            if git_blob is not None and relative not in self._git_dirty
            else _stream_hash(path)
        )
        self._hash_cache[key] = value
        return value

    @staticmethod
    def _excluded(path: PurePosixPath) -> bool:
        lowered_parts = tuple(part.casefold() for part in path.parts)
        if {".git", ".quality-cache", "node_modules", "__pycache__"} & set(lowered_parts):
            return True
        for part in lowered_parts:
            if part == ".env.example":
                continue
            if (
                part in _SECRET_NAMES
                or part.startswith(".env.")
                or part.endswith((".pem", ".key", ".p12", ".pfx"))
            ):
                return True
        return False

    def _entry(self, candidate: Path) -> FileFingerprint | None:
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            return None
        relative = candidate.relative_to(self.root).as_posix()
        if self._excluded(PurePosixPath(relative)):
            return None
        mode = stat.S_IMODE(metadata.st_mode)
        entry_type = "symlink" if stat.S_ISLNK(metadata.st_mode) else "file"
        key = (relative, mode, metadata.st_size, metadata.st_mtime_ns, entry_type)
        cached = self._entry_cache.get(key)
        if cached is not None:
            return cached
        if entry_type == "symlink":
            entry = self._symlink_entry(candidate)
        elif stat.S_ISREG(metadata.st_mode):
            entry = FileFingerprint(
                path=relative,
                type="file",
                mode=f"{mode:04o}",
                size=metadata.st_size,
                sha256=self._hash_file(
                    candidate,
                    mode,
                    metadata.st_size,
                    metadata.st_mtime_ns,
                ),
            )
        else:
            return None
        self._entry_cache[key] = entry
        return entry

    def _walk_directory(self, directory: Path) -> tuple[Path, ...]:
        candidates: list[Path] = []
        if not directory.is_dir() or directory.is_symlink():
            return ()
        for current_path, directory_names, file_names in os.walk(
            directory,
            topdown=True,
            followlinks=False,
        ):
            current = Path(current_path)
            directory_names[:] = sorted(
                name
                for name in directory_names
                if not self._excluded(
                    PurePosixPath((current / name).relative_to(self.root).as_posix())
                )
            )
            for name in tuple(directory_names):
                candidate = current / name
                if candidate.is_symlink():
                    candidates.append(candidate)
                    directory_names.remove(name)
            candidates.extend(current / name for name in sorted(file_names))
        return tuple(candidates)

    def _pattern_candidates(self, pattern: str) -> tuple[Path, ...]:
        self._load_git_index()
        if self._git_inventory_available:
            return tuple(
                self.root.joinpath(*PurePosixPath(path).parts)
                for path in sorted(self._git_paths)
                if matches_repository_path(path, pattern)
            )

        parts = PurePosixPath(pattern).parts
        first_glob = next(
            (
                index
                for index, part in enumerate(parts)
                if any(marker in part for marker in _GLOB_MARKERS)
            ),
            None,
        )
        if first_glob is None:
            candidate = self.root.joinpath(*parts)
            if candidate.is_dir() and not candidate.is_symlink():
                return self._walk_directory(candidate)
            return (candidate,) if candidate.exists() or candidate.is_symlink() else ()
        prefix_parts = parts[:first_glob]
        base = self.root.joinpath(*prefix_parts)
        remaining_parts = parts[first_glob:]
        if remaining_parts == ("**",):
            return self._walk_directory(base)
        if len(remaining_parts) == 1:
            if not base.is_dir():
                return ()
            return tuple(
                candidate
                for candidate in base.iterdir()
                if matches_repository_path(candidate.relative_to(self.root).as_posix(), pattern)
            )
        return tuple(
            candidate
            for candidate in self._walk_directory(base)
            if matches_repository_path(candidate.relative_to(self.root).as_posix(), pattern)
        )

    def entries_for_pattern(self, pattern: str) -> tuple[FileFingerprint, ...]:
        cached = self._pattern_cache.get(pattern)
        if cached is not None:
            return cached
        entries: dict[str, FileFingerprint] = {}
        for candidate in self._pattern_candidates(pattern):
            relative = candidate.relative_to(self.root)
            if self._excluded(PurePosixPath(relative.as_posix())):
                continue
            if candidate.is_symlink() or candidate.is_file():
                entry = self._entry(candidate)
                if entry is not None:
                    entries[entry.path] = entry
        value = tuple(sorted(entries.values(), key=lambda entry: entry.path))
        self._pattern_cache[pattern] = value
        return value

    def entries_for_patterns(
        self,
        patterns: tuple[str, ...],
    ) -> tuple[FileFingerprint, ...]:
        entries: dict[str, FileFingerprint] = {}
        for pattern in patterns:
            for entry in self.entries_for_pattern(pattern):
                entries[entry.path] = entry
        return tuple(sorted(entries.values(), key=lambda entry: entry.path))

    def _symlink_entry(self, path: Path) -> FileFingerprint:
        metadata = path.lstat()
        link_target = os.readlink(path)
        if link_target.startswith("\\\\?\\"):
            link_target = link_target[4:]
        return FileFingerprint(
            path=path.relative_to(self.root).as_posix(),
            type="symlink",
            mode=f"{stat.S_IMODE(metadata.st_mode):04o}",
            size=metadata.st_size,
            link_target=link_target,
        )

    def toolchain_identity(self, runner: Runner) -> dict[str, str]:
        if self._toolchain_override is not None:
            return self._toolchain_override.copy()
        cached = self._toolchain_cache.get(runner)
        if cached is not None:
            return cached.copy()
        identity = {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        }
        package_by_runner = {
            Runner.RUFF: "ruff",
            Runner.RUFF_FORMAT: "ruff",
            Runner.MYPY: "mypy",
            Runner.VULTURE: "vulture",
            Runner.PYTEST: "pytest",
            Runner.PLAYWRIGHT: "playwright",
        }
        package = package_by_runner.get(runner)
        if package:
            try:
                identity[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                identity[package] = "missing"
        if runner in {Runner.PNPM, Runner.VITEST, Runner.PLAYWRIGHT}:
            identity.update(self._javascript_identity())
        identity["runner"] = runner.value
        self._toolchain_cache[runner] = dict(sorted(identity.items()))
        return self._toolchain_cache[runner].copy()

    @staticmethod
    def _javascript_identity() -> dict[str, str]:
        identity: dict[str, str] = {}
        for executable in ("node", "pnpm"):
            resolved = shutil.which(executable)
            if resolved is None:
                identity[executable] = "missing"
                continue
            try:
                completed = subprocess.run(
                    [resolved, "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                identity[executable] = (
                    completed.stdout.strip()
                    or completed.stderr.strip()
                    or f"exit-{completed.returncode}"
                )
            except (OSError, subprocess.TimeoutExpired):
                identity[executable] = "unavailable"
        return identity


def fingerprint_patterns(
    repository_root: str | Path,
    patterns: list[str] | tuple[str, ...],
    *,
    context: FingerprintContext | None = None,
) -> PatternFingerprint:
    active_context = context or FingerprintContext(repository_root)
    root = Path(repository_root).resolve()
    if active_context.root != root:
        raise ValueError("fingerprint context belongs to a different repository root")
    normalized_patterns = tuple(sorted({_normalize_pattern(item) for item in patterns}))
    entries = active_context.entries_for_patterns(normalized_patterns)
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "patterns": normalized_patterns,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    return PatternFingerprint(
        digest=_digest(payload),
        file_count=len(entries),
        patterns=normalized_patterns,
        paths=tuple(entry.path for entry in entries),
        entries=entries,
    )


def _component_input_patterns(catalog: Catalog, group_id: str) -> tuple[str, ...]:
    relevant = {
        component_id
        for component_id, component in catalog.components.items()
        if group_id in component.direct_groups
    }
    changed = True
    while changed:
        changed = False
        for component_id, component in catalog.components.items():
            if component_id in relevant:
                continue
            if any(impacted_id in relevant for impacted_id in component.impacts):
                relevant.add(component_id)
                changed = True
    return tuple(
        sorted(
            {
                pattern
                for component_id in relevant
                for pattern in catalog.components[component_id].paths
            }
        )
    )


def group_input_patterns(catalog: Catalog, group_id: str) -> tuple[str, ...]:
    group = catalog.groups[group_id]
    patterns = set(_component_input_patterns(catalog, group_id))
    patterns.update(group.targets)
    if group.entrypoint:
        patterns.add(group.entrypoint)
    for input_set_id in (*catalog.default_input_sets, *group.input_sets):
        patterns.update(catalog.input_sets[input_set_id].paths)
    return tuple(sorted(patterns))


def fingerprint_group(
    context: FingerprintContext,
    catalog: Catalog,
    manifest_hash: str,
    group_id: str,
    dependency_fingerprints: Mapping[str, str],
    *,
    extra_input_patterns: tuple[str, ...] = (),
    change_identity: tuple[Change, ...] = (),
) -> GroupFingerprint:
    group = catalog.groups[group_id]
    missing_dependencies = set(group.depends_on) - set(dependency_fingerprints)
    if missing_dependencies:
        raise ValueError(
            f"missing dependency fingerprints for {group_id!r}: "
            f"{', '.join(sorted(missing_dependencies))}"
        )
    unexpected_dependencies = set(dependency_fingerprints) - set(group.depends_on)
    if unexpected_dependencies:
        raise ValueError(
            f"unexpected dependency fingerprints for {group_id!r}: "
            f"{', '.join(sorted(unexpected_dependencies))}"
        )
    patterns = tuple(sorted({*group_input_patterns(catalog, group_id), *extra_input_patterns}))
    files = fingerprint_patterns(context.root, patterns, context=context)
    toolchain = context.toolchain_identity(group.runner)
    dependencies = dict(sorted(dependency_fingerprints.items()))
    payload = {
        "schema_version": FINGERPRINT_SCHEMA_VERSION,
        "group_id": group_id,
        "manifest_hash": manifest_hash,
        "command": group.model_dump(mode="json"),
        "file_digest": files.digest,
        "toolchain_identity": toolchain,
        "dependency_fingerprints": dependencies,
        "change_identity": [change.model_dump(mode="json") for change in change_identity],
    }
    return GroupFingerprint(
        digest=_digest(payload),
        file_digest=files.digest,
        file_count=files.file_count,
        patterns=patterns,
        toolchain_identity=toolchain,
        dependency_fingerprints=dependencies,
    )
