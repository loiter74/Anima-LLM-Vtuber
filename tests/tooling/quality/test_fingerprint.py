from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from tooling.quality.fingerprint import (
    FingerprintContext,
    fingerprint_group,
    fingerprint_patterns,
)
from tooling.quality.models import Catalog


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _catalog(*, args: list[str] | None = None) -> Catalog:
    return Catalog.model_validate(
        {
            "schema_version": 1,
            "input_sets": {
                "toolchain": {"paths": ["pyproject.toml"]},
            },
            "default_input_sets": ["toolchain"],
            "groups": {
                "group-a": {
                    "domain": "backend",
                    "kind": "unit",
                    "runner": "pytest",
                    "targets": ["tests/a"],
                    "args": args or ["-q"],
                    "input_sets": ["toolchain"],
                    "depends_on": ["prerequisite"],
                },
                "group-b": {
                    "domain": "backend",
                    "kind": "unit",
                    "runner": "pytest",
                    "targets": ["tests/b"],
                },
                "prerequisite": {
                    "domain": "repository",
                    "kind": "contract",
                    "runner": "python",
                    "entrypoint": "scripts/prerequisite.py",
                },
            },
            "components": {
                "component-a": {
                    "domain": "backend",
                    "paths": ["src/a/**"],
                    "direct_groups": ["group-a"],
                },
                "component-b": {
                    "domain": "backend",
                    "paths": ["src/b/**"],
                    "direct_groups": ["group-b"],
                },
                "component-upstream": {
                    "domain": "backend",
                    "paths": ["src/shared/**"],
                    "direct_groups": ["prerequisite"],
                    "impacts": ["component-a"],
                },
            },
            "fallbacks": {
                "backend": ["group-a"],
                "frontend": ["group-b"],
                "repository": ["prerequisite"],
            },
        }
    )


def _context(root: Path, identity: str = "toolchain-v1") -> FingerprintContext:
    return FingerprintContext(root, toolchain_identity_override={"test": identity})


def _seed_group_files(root: Path) -> None:
    _write(root / "pyproject.toml", "[project]\nname='fingerprint-test'\n")
    _write(root / "src/a/module.py", "VALUE = 'a'\n")
    _write(root / "src/b/module.py", "VALUE = 'b'\n")
    _write(root / "src/shared/base.py", "SHARED = 1\n")
    _write(root / "tests/a/test_a.py", "def test_a(): pass\n")
    _write(root / "tests/b/test_b.py", "def test_b(): pass\n")
    _write(root / "scripts/prerequisite.py", "print('ok')\n")


def test_pattern_fingerprint_is_ordered_deduplicated_and_separator_stable(
    tmp_path: Path,
) -> None:
    _write(tmp_path / "src/z.py", "z\n")
    _write(tmp_path / "src/a.py", "a\n")

    first = fingerprint_patterns(tmp_path, ["src/**", "src/a.py"])
    second = fingerprint_patterns(tmp_path, ["src\\a.py", "src\\**"])

    assert first.digest == second.digest
    assert first.paths == ("src/a.py", "src/z.py")
    assert first.file_count == 2


def test_trailing_recursive_glob_hashes_deeply_nested_files(tmp_path: Path) -> None:
    target = tmp_path / "frontend/src/components/live2d/useLive2D.ts"
    _write(target, "export const listenerCount = 1\n")

    first = fingerprint_patterns(tmp_path, ["frontend/**"])
    assert first.paths == ("frontend/src/components/live2d/useLive2D.ts",)

    _write(target, "export const listenerCount = 2\n")
    changed = fingerprint_patterns(tmp_path, ["frontend/**"])
    assert changed.digest != first.digest


def test_recursive_glob_never_hashes_secret_files(tmp_path: Path) -> None:
    _write(tmp_path / "frontend/src/app.ts", "export const app = true\n")
    _write(tmp_path / "frontend/.env", "API_KEY=do-not-hash\n")

    fingerprint = fingerprint_patterns(tmp_path, ["frontend/**"])

    assert fingerprint.paths == ("frontend/src/app.ts",)


@pytest.mark.skipif(shutil.which("git") is None, reason="git is unavailable")
def test_git_inventory_excludes_ignored_generated_files(tmp_path: Path) -> None:
    _write(tmp_path / ".gitignore", ".env\ndist/\ntest-results/\n*.log\n")
    source = tmp_path / "frontend/src/components/app.ts"
    _write(source, "export const app = 1\n")
    _write(tmp_path / "frontend/.env", "API_KEY=do-not-hash\n")
    generated = tmp_path / "frontend/dist/app.js"
    _write(generated, "generated-v1\n")
    _write(tmp_path / "frontend/test-results/result.json", "{}\n")
    _write(tmp_path / "frontend/vite.log", "runtime-v1\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)

    first = fingerprint_patterns(tmp_path, ["frontend/**"])
    assert first.paths == ("frontend/src/components/app.ts",)

    _write(generated, "generated-v2\n")
    _write(tmp_path / "frontend/vite.log", "runtime-v2\n")
    ignored_changed = fingerprint_patterns(tmp_path, ["frontend/**"])
    assert ignored_changed.digest == first.digest

    _write(source, "export const app = 2\n")
    source_changed = fingerprint_patterns(tmp_path, ["frontend/**"])
    assert source_changed.digest != first.digest


def test_fingerprint_changes_for_content_type_and_mode(tmp_path: Path) -> None:
    target = tmp_path / "src/value.py"
    _write(target, "one\n")
    first = fingerprint_patterns(tmp_path, ["src/**"])

    _write(target, "two\n")
    content_changed = fingerprint_patterns(tmp_path, ["src/**"])
    assert content_changed.digest != first.digest

    before_mode = stat.S_IMODE(target.lstat().st_mode)
    os.chmod(target, before_mode ^ stat.S_IXUSR)
    after_mode = stat.S_IMODE(target.lstat().st_mode)
    if after_mode != before_mode:
        mode_changed = fingerprint_patterns(tmp_path, ["src/**"])
        assert mode_changed.digest != content_changed.digest

    target.unlink()
    target.mkdir()
    _write(target / "nested.txt", "two\n")
    type_changed = fingerprint_patterns(tmp_path, ["src/**"])
    assert type_changed.digest != content_changed.digest


def test_symlink_is_hashed_without_following_target_outside_repository(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repo"
    outside = tmp_path / "outside.txt"
    repository.mkdir()
    outside.write_text("secret-one", encoding="utf-8")
    link = repository / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    first = fingerprint_patterns(repository, ["link.txt"])
    outside.write_text("secret-two", encoding="utf-8")
    second = fingerprint_patterns(repository, ["link.txt"])

    assert first.digest == second.digest
    assert first.entries[0].type == "symlink"
    assert first.entries[0].link_target == str(outside)


def test_untracked_delete_and_rename_each_change_fingerprint(tmp_path: Path) -> None:
    original = tmp_path / "src/original.py"
    _write(original, "value\n")
    first = fingerprint_patterns(tmp_path, ["src/**"])

    _write(tmp_path / "src/untracked.py", "new\n")
    untracked = fingerprint_patterns(tmp_path, ["src/**"])
    assert untracked.digest != first.digest

    (tmp_path / "src/untracked.py").unlink()
    original.rename(tmp_path / "src/renamed.py")
    renamed = fingerprint_patterns(tmp_path, ["src/**"])
    assert renamed.digest != first.digest

    (tmp_path / "src/renamed.py").unlink()
    deleted = fingerprint_patterns(tmp_path, ["src/**"])
    assert deleted.digest != renamed.digest


def test_group_fingerprint_uses_relevant_component_and_upstream_closure_only(
    tmp_path: Path,
) -> None:
    _seed_group_files(tmp_path)
    catalog = _catalog()
    first = fingerprint_group(
        _context(tmp_path), catalog, "manifest-v1", "group-a", {"prerequisite": "p1"}
    )

    _write(tmp_path / "src/b/module.py", "UNRELATED = 2\n")
    unrelated = fingerprint_group(
        _context(tmp_path), catalog, "manifest-v1", "group-a", {"prerequisite": "p1"}
    )
    assert unrelated.digest == first.digest

    _write(tmp_path / "src/shared/base.py", "SHARED = 2\n")
    upstream = fingerprint_group(
        _context(tmp_path), catalog, "manifest-v1", "group-a", {"prerequisite": "p1"}
    )
    assert upstream.digest != first.digest


@pytest.mark.parametrize("changed_input", ["source", "test", "config"])
def test_group_fingerprint_invalidates_relevant_files(
    tmp_path: Path,
    changed_input: str,
) -> None:
    _seed_group_files(tmp_path)
    catalog = _catalog()
    first = fingerprint_group(
        _context(tmp_path), catalog, "manifest-v1", "group-a", {"prerequisite": "p1"}
    )
    paths = {
        "source": tmp_path / "src/a/module.py",
        "test": tmp_path / "tests/a/test_a.py",
        "config": tmp_path / "pyproject.toml",
    }
    _write(paths[changed_input], f"changed-{changed_input}\n")

    changed = fingerprint_group(
        _context(tmp_path), catalog, "manifest-v1", "group-a", {"prerequisite": "p1"}
    )
    assert changed.digest != first.digest


def test_group_fingerprint_binds_command_manifest_toolchain_and_dependencies(
    tmp_path: Path,
) -> None:
    _seed_group_files(tmp_path)
    baseline = fingerprint_group(
        _context(tmp_path), _catalog(), "manifest-v1", "group-a", {"prerequisite": "p1"}
    )

    command = fingerprint_group(
        _context(tmp_path),
        _catalog(args=["-q", "-k", "focused"]),
        "manifest-v1",
        "group-a",
        {"prerequisite": "p1"},
    )
    manifest = fingerprint_group(
        _context(tmp_path), _catalog(), "manifest-v2", "group-a", {"prerequisite": "p1"}
    )
    toolchain = fingerprint_group(
        _context(tmp_path, "toolchain-v2"),
        _catalog(),
        "manifest-v1",
        "group-a",
        {"prerequisite": "p1"},
    )
    dependency = fingerprint_group(
        _context(tmp_path), _catalog(), "manifest-v1", "group-a", {"prerequisite": "p2"}
    )

    assert (
        len({baseline.digest, command.digest, manifest.digest, toolchain.digest, dependency.digest})
        == 5
    )
