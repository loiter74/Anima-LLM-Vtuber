from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from animetta.services.program_script import ProgramScriptRepository, ProgramScriptRepositoryError

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def repository(tmp_path: Path) -> ProgramScriptRepository:
    return ProgramScriptRepository(
        tmp_path,
        builtin_dir=PROJECT_ROOT / "config" / "program_scripts",
    )


def test_copy_save_publish_and_duplicate_version_are_atomic(tmp_path: Path) -> None:
    store = repository(tmp_path)
    draft = store.duplicate_version(
        "aura-debut-memory",
        1,
        new_id="aura-custom",
        title="自定义 Aura",
    )
    draft.script.description = "第一次编辑"
    saved = store.save_draft(
        "aura-custom",
        expected_revision=1,
        script=draft.script,
    )
    published = store.publish("aura-custom", expected_revision=saved.revision)

    assert published.version == 1
    assert len(published.content_hash) == 64
    assert not (tmp_path / "aura-custom" / "draft.yaml").exists()
    assert (tmp_path / "aura-custom" / "versions" / "v1.yaml").is_file()

    next_draft = store.duplicate_version("aura-custom", 1)
    next_draft.script.description = "第二次编辑"
    saved_next = store.save_draft(
        "aura-custom",
        expected_revision=1,
        script=next_draft.script,
    )
    published_next = store.publish("aura-custom", expected_revision=saved_next.revision)

    assert published_next.version == 2
    assert store.get_published("aura-custom", 1).script.description == "第一次编辑"


def test_stale_revision_is_rejected_without_overwriting(tmp_path: Path) -> None:
    store = repository(tmp_path)
    draft = store.duplicate_version("aura-debut-memory", 1, new_id="revision-test")
    saved = store.save_draft("revision-test", expected_revision=1, script=draft.script)

    with pytest.raises(ProgramScriptRepositoryError) as exc_info:
        store.save_draft("revision-test", expected_revision=1, script=saved.script)

    assert exc_info.value.code == "revision_conflict"
    assert store.get_draft("revision-test").revision == 2


def test_builtin_version_is_read_only(tmp_path: Path) -> None:
    store = repository(tmp_path)
    script = store.get_published("aura-debut-memory", 1).script

    with pytest.raises(ProgramScriptRepositoryError) as exc_info:
        store.create_draft(script)

    assert exc_info.value.code == "builtin_read_only"


def test_duplicate_revalidates_the_new_identity(tmp_path: Path) -> None:
    store = repository(tmp_path)

    with pytest.raises(ValidationError):
        store.duplicate_version("aura-debut-memory", 1, new_id="Not valid")
