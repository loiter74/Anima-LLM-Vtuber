from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

from .models import Change, ChangeSet, ChangeStatus


class ChangeDiscoveryError(RuntimeError):
    """Raised when Git cannot provide a trustworthy change set."""


def normalize_repo_path(path: str | Path, repo_root: str | Path) -> str:
    root = Path(repo_root).resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            candidate = candidate.resolve().relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path is outside repository: {path}") from exc
        raw = candidate.as_posix()
    else:
        raw = str(path).replace("\\", "/")
        while raw.startswith("./"):
            raw = raw[2:]

    normalized = PurePosixPath(raw)
    if not raw or normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"path must be repository-relative: {path}")
    return normalized.as_posix()


def from_paths(paths: Iterable[str | Path], *, repo_root: str | Path) -> ChangeSet:
    normalized = sorted({normalize_repo_path(path, repo_root) for path in paths})
    return ChangeSet(
        changes=tuple(Change(path=path, status=ChangeStatus.MODIFIED) for path in normalized),
        source="paths",
    )


def _run_git(repo_root: Path, *args: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
        )
    except OSError as exc:
        raise ChangeDiscoveryError(
            f"unable to execute git: {type(exc).__name__}: {exc}"
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ChangeDiscoveryError(stderr or f"git {' '.join(args)} failed")
    return completed.stdout


def _resolve_revision(repo_root: Path, revision: str) -> str:
    try:
        output = _run_git(repo_root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except ChangeDiscoveryError as exc:
        raise ChangeDiscoveryError(f"unable to resolve revision {revision!r}: {exc}") from exc
    return output.decode("ascii").strip()


def _parse_name_status(payload: bytes, repo_root: Path) -> list[Change]:
    fields = payload.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        status_token = fields[index].decode("ascii", errors="replace")
        index += 1
        status_code = status_token[:1]
        if status_code in {"R", "C"}:
            if index + 1 >= len(fields):
                raise ChangeDiscoveryError("truncated Git rename record")
            old_path = normalize_repo_path(fields[index].decode("utf-8"), repo_root)
            new_path = normalize_repo_path(fields[index + 1].decode("utf-8"), repo_root)
            index += 2
            changes.append(
                Change(path=new_path, old_path=old_path, status=ChangeStatus.RENAMED)
            )
            continue
        if index >= len(fields):
            raise ChangeDiscoveryError("truncated Git name-status record")
        path = normalize_repo_path(fields[index].decode("utf-8"), repo_root)
        index += 1
        status = {
            "A": ChangeStatus.ADDED,
            "D": ChangeStatus.DELETED,
            "M": ChangeStatus.MODIFIED,
            "T": ChangeStatus.MODIFIED,
            "U": ChangeStatus.MODIFIED,
        }.get(status_code, ChangeStatus.MODIFIED)
        changes.append(Change(path=path, status=status))
    return changes


def _deduplicate(changes: Iterable[Change]) -> tuple[Change, ...]:
    by_path: dict[str, Change] = {}
    for change in changes:
        by_path[change.path] = change
    return tuple(by_path[path] for path in sorted(by_path))


def discover_worktree(repo_root: str | Path) -> ChangeSet:
    root = Path(repo_root).resolve()
    tracked = _parse_name_status(
        _run_git(root, "diff", "--name-status", "-z", "--find-renames", "HEAD"),
        root,
    )
    untracked_payload = _run_git(root, "ls-files", "--others", "--exclude-standard", "-z")
    untracked = [
        Change(
            path=normalize_repo_path(field.decode("utf-8"), root),
            status=ChangeStatus.ADDED,
        )
        for field in untracked_payload.split(b"\0")
        if field
    ]
    head_sha = _resolve_revision(root, "HEAD")
    return ChangeSet(
        changes=_deduplicate((*tracked, *untracked)),
        source="worktree",
        head_sha=head_sha,
    )


def discover_range(repo_root: str | Path, base_sha: str, head_sha: str) -> ChangeSet:
    root = Path(repo_root).resolve()
    resolved_base = _resolve_revision(root, base_sha)
    resolved_head = _resolve_revision(root, head_sha)
    payload = _run_git(
        root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        f"{resolved_base}...{resolved_head}",
    )
    return ChangeSet(
        changes=_deduplicate(_parse_name_status(payload, root)),
        source="range",
        base_sha=resolved_base,
        head_sha=resolved_head,
    )
