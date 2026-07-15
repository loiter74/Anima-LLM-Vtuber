from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tooling.quality.change_sources import (
    ChangeDiscoveryError,
    discover_range,
    discover_worktree,
    from_paths,
)
from tooling.quality.models import ChangeStatus

ROOT = Path(__file__).resolve().parents[3]


def test_repository_ignores_quality_generated_worktree_outputs() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "artifacts/test-impact/" in gitignore
    assert "evidence/runtime-config/" in gitignore
    assert "coverage.xml" in gitignore
    assert "junit.xml" in gitignore


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "quality@example.com")
    _git(repo, "config", "user.name", "Quality Tests")
    return repo


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def test_explicit_paths_are_normalized_deduplicated_and_sorted(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    absolute = repo / "src" / "animetta" / "core" / "service.py"

    changes = from_paths(
        [
            "src\\animetta\\core\\service.py",
            str(absolute),
            "frontend/src/中文 file.vue",
            "src/animetta/core/service.py",
        ],
        repo_root=repo,
    )

    assert [change.path for change in changes.changes] == [
        "frontend/src/中文 file.vue",
        "src/animetta/core/service.py",
    ]
    assert {change.status for change in changes.changes} == {ChangeStatus.MODIFIED}


def test_worktree_discovers_staged_unstaged_untracked_deleted_and_renamed(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    for name in ("staged.py", "unstaged.py", "deleted.py", "rename.py"):
        (repo / name).write_text(f"{name}\n", encoding="utf-8")
    _commit_all(repo, "baseline")

    (repo / "staged.py").write_text("staged changed\n", encoding="utf-8")
    _git(repo, "add", "staged.py")
    (repo / "unstaged.py").write_text("unstaged changed\n", encoding="utf-8")
    (repo / "deleted.py").unlink()
    _git(repo, "mv", "rename.py", "renamed 文件.py")
    (repo / "untracked file.py").write_text("new\n", encoding="utf-8")

    change_set = discover_worktree(repo)
    by_path = {change.path: change for change in change_set.changes}

    assert by_path["staged.py"].status is ChangeStatus.MODIFIED
    assert by_path["unstaged.py"].status is ChangeStatus.MODIFIED
    assert by_path["deleted.py"].status is ChangeStatus.DELETED
    assert by_path["renamed 文件.py"].status is ChangeStatus.RENAMED
    assert by_path["renamed 文件.py"].old_path == "rename.py"
    assert by_path["untracked file.py"].status is ChangeStatus.ADDED


def test_revision_range_discovers_rename_delete_add_and_modify(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "modify.py").write_text("before\n", encoding="utf-8")
    (repo / "delete.py").write_text("delete\n", encoding="utf-8")
    (repo / "rename.py").write_text("rename\n", encoding="utf-8")
    base = _commit_all(repo, "baseline")

    (repo / "modify.py").write_text("after\n", encoding="utf-8")
    (repo / "delete.py").unlink()
    _git(repo, "mv", "rename.py", "renamed.py")
    (repo / "added.py").write_text("added\n", encoding="utf-8")
    head = _commit_all(repo, "changes")

    change_set = discover_range(repo, base, head)
    by_path = {change.path: change for change in change_set.changes}

    assert by_path["modify.py"].status is ChangeStatus.MODIFIED
    assert by_path["delete.py"].status is ChangeStatus.DELETED
    assert by_path["added.py"].status is ChangeStatus.ADDED
    assert by_path["renamed.py"].status is ChangeStatus.RENAMED
    assert by_path["renamed.py"].old_path == "rename.py"
    assert change_set.base_sha == base
    assert change_set.head_sha == head


def test_revision_range_reports_missing_revision(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "tracked.py").write_text("tracked\n", encoding="utf-8")
    head = _commit_all(repo, "baseline")

    with pytest.raises(ChangeDiscoveryError, match="missing-base"):
        discover_range(repo, "missing-base", head)


def test_git_executable_failure_is_wrapped_as_discovery_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def missing_git(*args, **kwargs):
        raise FileNotFoundError("git executable missing")

    monkeypatch.setattr("tooling.quality.change_sources.subprocess.run", missing_git)

    with pytest.raises(ChangeDiscoveryError, match="unable to execute git"):
        discover_worktree(tmp_path)
