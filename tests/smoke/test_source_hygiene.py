from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = ROOT / "src" / "animetta"
SCRIPTS_ROOT = ROOT / "scripts"


def _python_sources() -> list[Path]:
    return sorted(SOURCE_ROOT.rglob("*.py"))


def _runtime_python_sources() -> list[Path]:
    return sorted([*SOURCE_ROOT.rglob("*.py"), *SCRIPTS_ROOT.rglob("*.py")])


def test_service_code_does_not_use_unsafe_tempfile_mktemp() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _python_sources()
        if "tempfile.mktemp" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_runtime_code_does_not_print_tracebacks_to_stdout() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _runtime_python_sources()
        if "traceback.print_exc" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_runtime_code_uses_logger_exception_instead_of_traceback_module() -> None:
    offenders = [
        str(path.relative_to(ROOT))
        for path in _runtime_python_sources()
        if "import traceback" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_server_routes_do_not_call_memory_private_methods() -> None:
    routes = SOURCE_ROOT / "orchestration" / "server" / "routes.py"
    content = routes.read_text(encoding="utf-8")

    assert "._run_metabolism_tick" not in content
