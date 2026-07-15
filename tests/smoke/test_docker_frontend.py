from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = ("Dockerfile",)


def test_docker_frontend_build_uses_pnpm_lockfile() -> None:
    offenders: list[str] = []

    for name in DOCKERFILES:
        content = (ROOT / name).read_text(encoding="utf-8")
        uses_npm_install = re.search(r"^\s*RUN\s+npm\s+install\b", content, re.MULTILINE)
        if (
            "pnpm install --frozen-lockfile" not in content
            or "pnpm-workspace.yaml" not in content
            or ".npmrc" not in content
            or "package-lock" in content
            or uses_npm_install
        ):
            offenders.append(name)

    assert offenders == []


def test_pnpm_workspace_allows_required_frontend_build_scripts() -> None:
    content = (ROOT / "frontend" / "pnpm-workspace.yaml").read_text(encoding="utf-8")

    for package in ("electron", "electron-winstaller", "esbuild", "vue-demi"):
        assert f"  {package}: true" in content

    assert "allowBuilds:" in content
    assert "onlyBuiltDependencies" not in content


def test_docker_frontend_build_skips_electron_binary_download() -> None:
    offenders: list[str] = []

    for name in DOCKERFILES:
        content = (ROOT / name).read_text(encoding="utf-8")
        if (
            "ELECTRON_SKIP_BINARY_DOWNLOAD=1" not in content
            or "npm_config_electron_skip_binary_download=true" not in content
        ):
            offenders.append(name)

    assert offenders == []


def test_frontend_npmrc_does_not_use_legacy_pnpm_build_policy() -> None:
    content = (ROOT / "frontend" / ".npmrc").read_text(encoding="utf-8")

    assert "onlyBuiltDependencies" not in content


def test_frontend_package_manager_is_pinned_to_pnpm() -> None:
    package_json = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))

    assert package_json["packageManager"].startswith("pnpm@")
