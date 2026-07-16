from __future__ import annotations

from pathlib import Path

import pytest

from tooling.quality.docker_plan import plan_docker_actions, select_docker_scopes
from tooling.quality.fingerprint import FingerprintContext
from tooling.quality.manifest import load_catalog
from tooling.quality.models import Change, ChangeSet, ChangeStatus, Tier

ROOT = Path(__file__).resolve().parents[3]


def _changes(
    path: str,
    *,
    status: ChangeStatus = ChangeStatus.MODIFIED,
    old_path: str | None = None,
) -> ChangeSet:
    return ChangeSet(
        changes=(Change(path=path, status=status, old_path=old_path),),
        source="paths",
    )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/animetta/core/service_pool.py", {"animetta"}),
        ("src/animetta/services/tts/remote_tts.py", {"animetta"}),
        ("frontend/src/App.vue", {"animetta"}),
        ("src/animetta_qwen_tts/app.py", {"qwen-tts"}),
        ("Dockerfile.qwen-tts", {"qwen-tts"}),
        ("src/animetta/config/loader.py", {"animetta", "qwen-tts"}),
        ("docker-compose.yml", {"animetta"}),
        ("docker-compose.qwen.yml", {"qwen-tts"}),
        ("docs/architecture.md", set()),
    ],
)
def test_selective_docker_scope_matrix(path: str, expected: set[str]) -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog

    selection = select_docker_scopes(catalog, _changes(path), Tier.AFFECTED)

    assert {item.scope_id for item in selection} == expected


def test_deleted_and_renamed_paths_consider_old_and_new_inputs() -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog

    deleted = select_docker_scopes(
        catalog,
        _changes(
            "src/animetta_qwen_tts/removed.py",
            status=ChangeStatus.DELETED,
        ),
        Tier.AFFECTED,
    )
    renamed = select_docker_scopes(
        catalog,
        _changes(
            "src/animetta_qwen_tts/moved.py",
            status=ChangeStatus.RENAMED,
            old_path="src/animetta/core/old.py",
        ),
        Tier.AFFECTED,
    )

    assert {item.scope_id for item in deleted} == {"qwen-tts"}
    assert {item.scope_id for item in renamed} == {"animetta", "qwen-tts"}


def test_unknown_watched_docker_input_fails_closed_to_all_scopes() -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog

    selection = select_docker_scopes(
        catalog,
        _changes("Dockerfile.experimental"),
        Tier.AFFECTED,
    )

    assert {item.scope_id for item in selection} == {"animetta", "qwen-tts"}
    assert all("unknown Docker input" in reason for item in selection for reason in item.reasons)


def test_minecraft_runtime_data_does_not_select_application_build_scope() -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog

    selection = select_docker_scopes(
        catalog,
        _changes("docker/minecraft-server/data/plugins/spark/profile.jfr.tmp"),
        Tier.AFFECTED,
    )

    assert selection == ()


def test_full_and_nightly_always_select_all_scopes() -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog
    irrelevant = _changes("docs/readme.md")

    for tier in (Tier.FULL, Tier.NIGHTLY):
        selection = select_docker_scopes(catalog, irrelevant, tier)
        assert {item.scope_id for item in selection} == {"animetta", "qwen-tts"}


def test_scope_fingerprint_changes_only_for_relevant_content(tmp_path: Path) -> None:
    manifest = tmp_path / "quality.yml"
    manifest.write_text(
        """
schema_version: 1
groups:
  check:
    domain: repository
    kind: smoke
    runner: python
    entrypoint: check.py
components:
  source:
    domain: repository
    paths: [src/**]
    direct_groups: [check]
fallbacks:
  backend: [check]
  frontend: [check]
  repository: [check]
docker_watch_paths: [Dockerfile*, src/a/**, src/b/**]
docker_scopes:
  a:
    service: a
    compose_file: docker-compose.a.yml
    environment_identity_fields: [A_PROFILE]
    paths: [Dockerfile.a, src/a/**]
  b:
    service: b
    compose_file: docker-compose.b.yml
    environment_identity_fields: [B_PROFILE]
    paths: [Dockerfile.b, src/b/**]
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile.a").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "Dockerfile.b").write_text("FROM scratch\n", encoding="utf-8")
    (tmp_path / "src/a/package").mkdir(parents=True)
    (tmp_path / "src/b/package").mkdir(parents=True)
    (tmp_path / "src/a/package/app.py").write_text("A=1\n", encoding="utf-8")
    (tmp_path / "src/b/package/app.py").write_text("B=1\n", encoding="utf-8")
    loaded = load_catalog(manifest)
    changes = _changes("src/a/package/app.py")

    first = plan_docker_actions(
        loaded.catalog,
        changes,
        Tier.AFFECTED,
        FingerprintContext(tmp_path, toolchain_identity_override={"docker": "v1"}),
    )
    (tmp_path / "src/b/package/app.py").write_text("B=2\n", encoding="utf-8")
    unrelated = plan_docker_actions(
        loaded.catalog,
        changes,
        Tier.AFFECTED,
        FingerprintContext(tmp_path, toolchain_identity_override={"docker": "v1"}),
    )
    (tmp_path / "src/a/package/app.py").write_text("A=2\n", encoding="utf-8")
    relevant = plan_docker_actions(
        loaded.catalog,
        changes,
        Tier.AFFECTED,
        FingerprintContext(tmp_path, toolchain_identity_override={"docker": "v1"}),
    )

    assert first[0].input_fingerprint == unrelated[0].input_fingerprint
    assert first[0].input_fingerprint != relevant[0].input_fingerprint


def test_catalogued_scopes_cover_actual_dockerfile_copy_inputs() -> None:
    catalog = load_catalog(ROOT / "tooling/quality.yml").catalog
    animetta = set(catalog.docker_scopes["animetta"].paths)
    qwen = set(catalog.docker_scopes["qwen-tts"].paths)

    assert {
        "Dockerfile",
        "requirements-core.txt",
        "frontend/**",
        "src/animetta/**",
        "config/**",
        "scripts/**",
        "docker/entrypoint.sh",
        "docker/nginx.conf",
        ".env.example",
        "docker-compose.yml",
        "docker-compose.cpu.yml",
        "docker-compose.core.yml",
    }.issubset(animetta)
    assert "docker/**" not in animetta
    assert {
        "Dockerfile.qwen-tts",
        "requirements-qwen-tts.txt",
        "src/animetta_qwen_tts/**",
        "src/animetta/config/**",
        "src/animetta/services/tts/__init__.py",
        "src/animetta/services/tts/audio_validation.py",
        "src/animetta/services/tts/interface.py",
        "src/animetta/services/tts/qwen3_tts.py",
        "config/**",
        "docker-compose.qwen.yml",
    }.issubset(qwen)
    assert "src/animetta/services/tts/**" not in qwen


def test_dependency_layers_precede_source_and_core_excludes_qwen_source() -> None:
    core_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    qwen_dockerfile = (ROOT / "Dockerfile.qwen-tts").read_text(encoding="utf-8")

    assert "COPY src/animetta/ src/animetta/" in core_dockerfile
    assert "COPY src/ src/" not in core_dockerfile
    requirements_copy = qwen_dockerfile.index("COPY requirements-qwen-tts.txt")
    dependency_install = qwen_dockerfile.index("pip install --user")
    source_copy = qwen_dockerfile.index("COPY src/animetta_qwen_tts/")
    assert requirements_copy < dependency_install < source_copy


def test_images_publish_plan_build_fingerprints_through_compose_args_and_labels() -> None:
    core_dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    qwen_dockerfile = (ROOT / "Dockerfile.qwen-tts").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    qwen_compose = (ROOT / "docker-compose.qwen.yml").read_text(encoding="utf-8")

    assert "ARG ANIMETTA_BUILD_FINGERPRINT" in core_dockerfile
    assert 'LABEL org.animetta.build-fingerprint="${ANIMETTA_BUILD_FINGERPRINT}"' in core_dockerfile
    assert "ARG QWEN_TTS_BUILD_FINGERPRINT" in qwen_dockerfile
    assert 'LABEL org.animetta.build-fingerprint="${QWEN_TTS_BUILD_FINGERPRINT}"' in qwen_dockerfile
    assert "ANIMETTA_BUILD_FINGERPRINT" in compose
    assert "QWEN_TTS_BUILD_FINGERPRINT" not in compose
    assert "QWEN_TTS_BUILD_FINGERPRINT" in qwen_compose
