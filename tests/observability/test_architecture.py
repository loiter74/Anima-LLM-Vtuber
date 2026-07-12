import ast
from pathlib import Path

ROOT = Path(__file__).parents[2]
OBSERVABILITY = ROOT / "src" / "animetta" / "observability"
FORBIDDEN_IMPORTS = (
    "animetta.orchestration",
    "animetta.services",
    "aiosqlite",
    "sqlite3",
    "opentelemetry",
    "prometheus_client",
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_domain_and_ports_have_no_runtime_or_infrastructure_dependencies() -> None:
    boundaries = [OBSERVABILITY / "domain.py", OBSERVABILITY / "ports.py"]
    assert all(path.is_file() for path in boundaries)

    violations = {
        str(path.relative_to(ROOT)): sorted(
            module
            for module in _imported_modules(path)
            if module.startswith(FORBIDDEN_IMPORTS)
        )
        for path in boundaries
    }

    assert not {path: imports for path, imports in violations.items() if imports}
