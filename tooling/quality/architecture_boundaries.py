"""Repository-wide production module boundary audit."""

from __future__ import annotations

import ast
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class BoundaryViolation:
    """One forbidden dependency or dependency cycle."""

    code: str
    path: PurePosixPath
    line: int
    message: str


_BACKEND_FORBIDDEN: dict[str, frozenset[str]] = {
    "services": frozenset({"core", "orchestration"}),
    "config": frozenset(
        {"core", "orchestration", "services", "memory", "tools", "avatar", "inspection"}
    ),
    "memory": frozenset({"core", "orchestration", "services", "tools", "avatar"}),
    "avatar": frozenset({"core", "orchestration", "services", "memory", "tools"}),
    "tools": frozenset({"core", "orchestration"}),
    "observability": frozenset({"core", "orchestration", "services", "memory", "avatar", "tools"}),
    "inspection": frozenset({"core", "orchestration", "services", "memory", "avatar", "tools"}),
}

# ADR-013 permits these terminal import facades for one released version. The
# canonical production tree must never import them; remove both entries when
# the compatibility window closes.
_COMPATIBILITY_FACADES = frozenset(
    {
        PurePosixPath("src/animetta/config/runtime_reload.py"),
        PurePosixPath("src/animetta/tools/minecraft/showcase/live.py"),
    }
)

_FRONTEND_IMPORT_RE = re.compile(r"(?:from\s+|import\s*\(\s*|import\s+)[\"']([^\"']+)[\"']")


def _backend_group(path: PurePosixPath) -> str | None:
    parts = path.parts
    try:
        offset = parts.index("animetta") + 1
    except ValueError:
        return None
    return parts[offset] if offset < len(parts) else None


def _frontend_group(path: PurePosixPath) -> str | None:
    parts = path.parts
    try:
        offset = parts.index("src") + 1
    except ValueError:
        return None
    if offset >= len(parts):
        return None
    first = parts[offset]
    if first == "features" and offset + 1 < len(parts):
        return f"features:{parts[offset + 1]}"
    return first


def _python_module(path: PurePosixPath) -> tuple[str, str]:
    relative = path.relative_to(PurePosixPath("src"))
    module_parts = relative.with_suffix("").parts
    module = ".".join(module_parts)
    package = ".".join(module_parts[:-1])
    if module_parts[-1] == "__init__":
        module = ".".join(module_parts[:-1])
        package = module
    return module, package


def _resolved_python_imports(
    path: PurePosixPath,
    source: str,
) -> tuple[tuple[int, str], ...]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ()
    _, package = _python_module(path)
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((node.lineno, alias.name) for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        try:
            imported = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module or ""
            )
        except (ImportError, ValueError):
            continue
        imports.append((node.lineno, imported))
    return tuple(imports)


def audit_python_source(
    path: PurePosixPath,
    source: str,
) -> tuple[BoundaryViolation, ...]:
    """Audit one tracked Python source file."""

    if path in _COMPATIBILITY_FACADES:
        return ()
    source_group = _backend_group(path)
    if source_group is None:
        return ()
    violations: list[BoundaryViolation] = []
    for line, imported in _resolved_python_imports(path, source):
        if imported == "animetta":
            target_group = None
        elif imported.startswith("animetta."):
            target_group = imported.split(".", 2)[1]
        else:
            target_group = None
        if target_group in _BACKEND_FORBIDDEN.get(source_group, frozenset()):
            violations.append(
                BoundaryViolation(
                    code="BACKEND_FORBIDDEN_IMPORT",
                    path=path,
                    line=line,
                    message=f"{source_group} must not import {imported}",
                )
            )
    return tuple(violations)


def _resolve_frontend_target(path: PurePosixPath, requested: str) -> PurePosixPath | None:
    if requested.startswith("@/"):
        return PurePosixPath("frontend/src") / requested[2:]
    if requested.startswith("."):
        return PurePosixPath(posixpath.normpath(str(path.parent / requested)))
    return None


def _frontend_rule(
    source_group: str,
    target_group: str,
    requested: str,
) -> tuple[str, str] | None:
    if source_group == "shared" and target_group != "shared":
        return "FRONTEND_SHARED_UPWARD_IMPORT", "shared may only import shared modules"
    if (
        source_group.startswith("features:")
        and target_group.startswith("features:")
        and source_group != target_group
        and requested.count("/") > 2
    ):
        return (
            "FRONTEND_CROSS_FEATURE_DEEP_IMPORT",
            "features may only consume another feature through its public entry",
        )
    if source_group == "stores" and target_group == "composables":
        return "FRONTEND_STORE_COMPOSABLE_IMPORT", "stores must not import composables"
    if source_group == "types" and target_group == "components":
        return "FRONTEND_TYPE_UI_IMPORT", "types must not import UI components"
    if source_group == "live" and (
        target_group.startswith("features:")
        or target_group
        in {
            "app",
            "components",
            "composables",
            "live2d-performance",
            "stores",
        }
    ):
        return (
            "FRONTEND_LIVE_DASHBOARD_IMPORT",
            "the formal live entry may only depend on shared/review/runtime-neutral modules",
        )
    if source_group == "live2d-performance" and target_group == "live":
        return (
            "FRONTEND_REVIEW_LIVE_IMPORT",
            "review tooling must consume a shared Live2D contract instead of live internals",
        )
    return None


def audit_frontend_source(
    path: PurePosixPath,
    source: str,
) -> tuple[BoundaryViolation, ...]:
    """Audit one TypeScript or Vue source file."""

    source_group = _frontend_group(path)
    if source_group is None:
        return ()
    violations: list[BoundaryViolation] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        for match in _FRONTEND_IMPORT_RE.finditer(line):
            requested = match.group(1)
            target_path = _resolve_frontend_target(path, requested)
            if target_path is None:
                continue
            target_group = _frontend_group(target_path)
            if target_group is None or target_group == source_group:
                continue
            rule = _frontend_rule(source_group, target_group, requested)
            if rule is None:
                continue
            code, message = rule
            violations.append(
                BoundaryViolation(
                    code=code,
                    path=path,
                    line=line_number,
                    message=f"{message}: {requested}",
                )
            )
    return tuple(violations)


def _strongly_connected_components(
    graph: dict[str, set[str]],
) -> tuple[tuple[str, ...], ...]:
    index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[tuple[str, ...]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] != indices[node]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1:
            components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return tuple(sorted(components))


def _repository_graphs(root: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    backend: dict[str, set[str]] = defaultdict(set)
    frontend: dict[str, set[str]] = defaultdict(set)
    for path in (root / "src" / "animetta").rglob("*.py"):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if relative in _COMPATIBILITY_FACADES:
            continue
        source_group = _backend_group(relative)
        if source_group is None:
            continue
        backend.setdefault(source_group, set())
        source = path.read_text(encoding="utf-8-sig")
        for _, imported in _resolved_python_imports(relative, source):
            if imported.startswith("animetta."):
                target_group = imported.split(".", 2)[1]
                if target_group != source_group:
                    backend[source_group].add(target_group)
    frontend_root = root / "frontend" / "src"
    for pattern in ("*.ts", "*.vue"):
        for path in frontend_root.rglob(pattern):
            if ".test." in path.name:
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            source_group = _frontend_group(relative)
            if source_group is None:
                continue
            frontend.setdefault(source_group, set())
            source = path.read_text(encoding="utf-8-sig")
            for match in _FRONTEND_IMPORT_RE.finditer(source):
                target_path = _resolve_frontend_target(relative, match.group(1))
                if target_path is None:
                    continue
                target_group = _frontend_group(target_path)
                if target_group is not None and target_group != source_group:
                    frontend[source_group].add(target_group)
    return backend, frontend


def audit_repository(root: Path) -> tuple[BoundaryViolation, ...]:
    """Audit all production Python, TypeScript and Vue sources."""

    violations: list[BoundaryViolation] = []
    for path in (root / "src" / "animetta").rglob("*.py"):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        violations.extend(audit_python_source(relative, path.read_text(encoding="utf-8-sig")))
    frontend_root = root / "frontend" / "src"
    for pattern in ("*.ts", "*.vue"):
        for path in frontend_root.rglob(pattern):
            if ".test." in path.name:
                continue
            relative = PurePosixPath(path.relative_to(root).as_posix())
            violations.extend(audit_frontend_source(relative, path.read_text(encoding="utf-8-sig")))

    backend, frontend = _repository_graphs(root)
    for component in _strongly_connected_components(backend):
        violations.append(
            BoundaryViolation(
                code="BACKEND_DEPENDENCY_CYCLE",
                path=PurePosixPath("src/animetta"),
                line=0,
                message="backend module cycle: " + " -> ".join(component),
            )
        )
    for component in _strongly_connected_components(frontend):
        violations.append(
            BoundaryViolation(
                code="FRONTEND_DEPENDENCY_CYCLE",
                path=PurePosixPath("frontend/src"),
                line=0,
                message="frontend module cycle: " + " -> ".join(component),
            )
        )
    return tuple(sorted(violations, key=lambda item: (str(item.path), item.line, item.code)))


def render_report(violations: tuple[BoundaryViolation, ...]) -> str:
    """Render deterministic console output for humans and quality tooling."""

    if not violations:
        return "Architecture boundary audit: no violations"
    lines = [f"Architecture boundary audit: {len(violations)} violation(s)"]
    lines.extend(f"- {item.code} {item.path}:{item.line}: {item.message}" for item in violations)
    return "\n".join(lines)
