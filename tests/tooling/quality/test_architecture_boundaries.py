from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath

from tooling.quality.architecture_boundaries import (
    audit_frontend_source,
    audit_python_source,
    audit_repository,
)


def _codes(violations: object) -> set[str]:
    return {item.code for item in violations}  # type: ignore[attr-defined]


def test_backend_domain_must_not_import_composition_or_orchestration() -> None:
    violations = audit_python_source(
        PurePosixPath("src/animetta/services/dialogue/service.py"),
        "from animetta.core.readiness import Status\n"
        "from animetta.orchestration.graph.state import AgentState\n",
    )

    assert _codes(violations) == {"BACKEND_FORBIDDEN_IMPORT"}


def test_backend_composition_root_may_import_application_and_domains() -> None:
    violations = audit_python_source(
        PurePosixPath("src/animetta/core/application.py"),
        "from animetta.orchestration.server.app import create_app\n"
        "from animetta.services.llm import LLMInterface\n",
    )

    assert violations == ()


def test_declared_one_release_compatibility_facade_is_terminal() -> None:
    violations = audit_python_source(
        PurePosixPath("src/animetta/config/runtime_reload.py"),
        "from animetta.services.runtime_config import RuntimePrompt\n",
    )

    assert violations == ()


def test_frontend_rejects_legacy_cycles_and_live_dashboard_dependencies() -> None:
    store = audit_frontend_source(
        PurePosixPath("frontend/src/stores/chat.ts"),
        "import { useSocket } from '@/composables/useSocket'\n",
    )
    contract = audit_frontend_source(
        PurePosixPath("frontend/src/types/socket-events.ts"),
        "export type { Plan } from '@/components/live2d/contract'\n",
    )
    live = audit_frontend_source(
        PurePosixPath("frontend/src/live/audio.ts"),
        "import { play } from '@/components/live2d/useAudioPlayback'\n",
    )

    assert _codes(store + contract + live) == {
        "FRONTEND_LIVE_DASHBOARD_IMPORT",
        "FRONTEND_STORE_COMPOSABLE_IMPORT",
        "FRONTEND_TYPE_UI_IMPORT",
    }


def test_frontend_shared_may_not_import_features() -> None:
    violations = audit_frontend_source(
        PurePosixPath("frontend/src/shared/transport/socket.ts"),
        "import { useChat } from '@/features/conversation'\n",
    )

    assert _codes(violations) == {"FRONTEND_SHARED_UPWARD_IMPORT"}


def test_repository_audit_reports_cross_package_cycles(tmp_path: Path) -> None:
    services = tmp_path / "src" / "animetta" / "services"
    core = tmp_path / "src" / "animetta" / "core"
    services.mkdir(parents=True)
    core.mkdir(parents=True)
    (services / "feature.py").write_text(
        "from animetta.core.application import app\n", encoding="utf-8"
    )
    (core / "application.py").write_text(
        "from animetta.services.feature import feature\n", encoding="utf-8"
    )
    (tmp_path / "frontend" / "src").mkdir(parents=True)

    violations = audit_repository(tmp_path)

    assert {item.code for item in violations} == {
        "BACKEND_DEPENDENCY_CYCLE",
        "BACKEND_FORBIDDEN_IMPORT",
    }


def test_report_cli_runs_from_repository_root() -> None:
    root = Path(__file__).resolve().parents[3]

    completed = subprocess.run(
        [sys.executable, "scripts/check_architecture_boundaries.py", "--report"],
        cwd=root,
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith("Architecture boundary audit:")
