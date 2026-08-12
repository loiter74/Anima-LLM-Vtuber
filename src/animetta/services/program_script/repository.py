"""Atomic YAML repository for mutable drafts and immutable script versions."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .models import (
    ProgramScript,
    ProgramScriptDraft,
    PublishedProgramScript,
    ValidationIssue,
    validate_program_script,
)


class ProgramScriptRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class ProgramScriptRepository:
    """Persist user scripts outside Git while exposing bundled read-only versions."""

    def __init__(self, root: Path, *, builtin_dir: Path | None = None) -> None:
        self.root = root.resolve()
        self.builtin_dir = builtin_dir.resolve() if builtin_dir else None

    def list_scripts(self) -> list[dict[str, Any]]:
        entries: dict[str, dict[str, Any]] = {}
        for published in self._builtin_versions():
            entries[published.script.id] = self._summary(published, archived=False)

        if self.root.is_dir():
            for script_dir in sorted(path for path in self.root.iterdir() if path.is_dir()):
                if _SCRIPT_ID.fullmatch(script_dir.name) is None:
                    continue
                versions = self._user_versions(script_dir.name)
                draft = self._load_draft_if_present(script_dir.name)
                if not versions and draft is None:
                    continue
                latest = versions[-1] if versions else None
                title = latest.script.title if latest else draft.script.title
                entries[script_dir.name] = {
                    "id": script_dir.name,
                    "title": title,
                    "description": latest.script.description
                    if latest
                    else draft.script.description,
                    "builtin": False,
                    "archived": self._is_archived(script_dir.name),
                    "draft_revision": draft.revision if draft else None,
                    "versions": [version.version for version in versions],
                }
        return sorted(entries.values(), key=lambda entry: (entry["archived"], entry["title"]))

    def create_draft(self, script: ProgramScript) -> ProgramScriptDraft:
        if self._draft_path(script.id).exists():
            raise ProgramScriptRepositoryError(
                "draft_exists", "该脚本已经存在草稿", status_code=409
            )
        if self._find_builtin(script.id, None) is not None:
            raise ProgramScriptRepositoryError(
                "builtin_read_only", "内置脚本不可直接编辑，请复制为新的脚本 ID", status_code=409
            )
        draft = ProgramScriptDraft(revision=1, script=script)
        self._write_yaml(self._draft_path(script.id), draft.model_dump(mode="json"))
        return draft

    def get_draft(self, script_id: str) -> ProgramScriptDraft:
        draft = self._load_draft_if_present(script_id)
        if draft is None:
            raise ProgramScriptRepositoryError("draft_not_found", "草稿不存在", status_code=404)
        return draft

    def save_draft(
        self,
        script_id: str,
        *,
        expected_revision: int,
        script: ProgramScript,
    ) -> ProgramScriptDraft:
        current = self.get_draft(script_id)
        if current.revision != expected_revision:
            raise ProgramScriptRepositoryError(
                "revision_conflict", "草稿已在其他页面更新", status_code=409
            )
        if script.id != script_id:
            raise ProgramScriptRepositoryError("script_id_mismatch", "保存时不能修改脚本 ID")
        updated = ProgramScriptDraft(revision=current.revision + 1, script=script)
        self._write_yaml(self._draft_path(script_id), updated.model_dump(mode="json"))
        return updated

    def validate_draft(self, script_id: str) -> list[ValidationIssue]:
        return validate_program_script(self.get_draft(script_id).script)

    def publish(self, script_id: str, *, expected_revision: int) -> PublishedProgramScript:
        draft = self.get_draft(script_id)
        if draft.revision != expected_revision:
            raise ProgramScriptRepositoryError(
                "revision_conflict", "草稿已在其他页面更新", status_code=409
            )
        issues = validate_program_script(draft.script)
        if issues:
            raise ProgramScriptRepositoryError(
                "validation_failed", "脚本校验未通过", status_code=422
            )

        versions = self._user_versions(script_id)
        version_number = versions[-1].version + 1 if versions else 1
        published = PublishedProgramScript(
            version=version_number,
            content_hash=_content_hash(draft.script),
            created_at=datetime.now(UTC).isoformat(),
            script=draft.script,
        )
        self._write_yaml(
            self._version_path(script_id, version_number),
            published.model_dump(mode="json"),
        )
        self._draft_path(script_id).unlink()
        return published

    def get_published(self, script_id: str, version: int) -> PublishedProgramScript:
        if version < 1:
            raise ProgramScriptRepositoryError("invalid_version", "版本号必须大于零")
        builtin = self._find_builtin(script_id, version)
        if builtin is not None:
            return builtin
        path = self._version_path(script_id, version)
        if not path.is_file():
            raise ProgramScriptRepositoryError(
                "version_not_found", "已发布版本不存在", status_code=404
            )
        return PublishedProgramScript.model_validate(self._read_yaml(path))

    def is_archived(self, script_id: str) -> bool:
        """Return whether a user-managed script is excluded from new runs."""
        return self._is_archived(script_id)

    def duplicate_version(
        self,
        script_id: str,
        version: int,
        *,
        new_id: str | None = None,
        title: str | None = None,
    ) -> ProgramScriptDraft:
        source = self.get_published(script_id, version)
        target_id = new_id or script_id
        payload = source.script.model_dump(mode="json")
        payload.update(
            {
                "id": target_id,
                "title": title or source.script.title,
            }
        )
        copied = ProgramScript.model_validate(payload)
        return self.create_draft(copied)

    def archive(self, script_id: str) -> None:
        if self._find_builtin(script_id, None) is not None:
            raise ProgramScriptRepositoryError(
                "builtin_read_only", "内置脚本不能归档", status_code=409
            )
        if not self._script_dir(script_id).is_dir():
            raise ProgramScriptRepositoryError("script_not_found", "脚本不存在", status_code=404)
        self._write_yaml(self._meta_path(script_id), {"archived": True})

    def _summary(
        self,
        published: PublishedProgramScript,
        *,
        archived: bool,
    ) -> dict[str, Any]:
        versions = [
            version.version
            for version in self._builtin_versions()
            if version.script.id == published.script.id
        ]
        return {
            "id": published.script.id,
            "title": published.script.title,
            "description": published.script.description,
            "builtin": True,
            "archived": archived,
            "draft_revision": None,
            "versions": versions,
        }

    def _builtin_versions(self) -> list[PublishedProgramScript]:
        if self.builtin_dir is None or not self.builtin_dir.is_dir():
            return []
        versions: list[PublishedProgramScript] = []
        for path in sorted(self.builtin_dir.glob("*.yaml")):
            data = self._read_yaml(path)
            script = ProgramScript.model_validate(data["script"])
            versions.append(
                PublishedProgramScript(
                    version=int(data.get("version", 1)),
                    content_hash=_content_hash(script),
                    created_at=str(data.get("created_at", "builtin")),
                    builtin=True,
                    script=script,
                )
            )
        return versions

    def _find_builtin(
        self,
        script_id: str,
        version: int | None,
    ) -> PublishedProgramScript | None:
        matches = [
            published
            for published in self._builtin_versions()
            if published.script.id == script_id
            and (version is None or published.version == version)
        ]
        return matches[-1] if matches else None

    def _user_versions(self, script_id: str) -> list[PublishedProgramScript]:
        versions_dir = self._script_dir(script_id) / "versions"
        if not versions_dir.is_dir():
            return []
        return [
            PublishedProgramScript.model_validate(self._read_yaml(path))
            for path in sorted(versions_dir.glob("v*.yaml"), key=_version_sort_key)
        ]

    def _load_draft_if_present(self, script_id: str) -> ProgramScriptDraft | None:
        path = self._draft_path(script_id)
        if not path.is_file():
            return None
        return ProgramScriptDraft.model_validate(self._read_yaml(path))

    def _is_archived(self, script_id: str) -> bool:
        path = self._meta_path(script_id)
        return bool(self._read_yaml(path).get("archived", False)) if path.is_file() else False

    def _script_dir(self, script_id: str) -> Path:
        if _SCRIPT_ID.fullmatch(script_id) is None:
            raise ProgramScriptRepositoryError("invalid_script_id", "脚本 ID 格式无效")
        return self.root / script_id

    def _draft_path(self, script_id: str) -> Path:
        return self._script_dir(script_id) / "draft.yaml"

    def _version_path(self, script_id: str, version: int) -> Path:
        return self._script_dir(script_id) / "versions" / f"v{version}.yaml"

    def _meta_path(self, script_id: str) -> Path:
        return self._script_dir(script_id) / "meta.yaml"

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as file:
            data = yaml.safe_load(file) or {}
        if not isinstance(data, dict):
            raise ValueError(f"expected a YAML object in {path}")
        return data

    @staticmethod
    def _write_yaml(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as file:
            yaml.safe_dump(data, file, allow_unicode=True, sort_keys=False)
        temporary.replace(path)


def _content_hash(script: ProgramScript) -> str:
    payload = json.dumps(
        script.model_dump(mode="json", exclude_none=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _version_sort_key(path: Path) -> int:
    try:
        return int(path.stem.removeprefix("v"))
    except ValueError:
        return 0


_SCRIPT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
