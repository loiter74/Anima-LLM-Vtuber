"""AST-based ownership audit for the Minecraft Voyager control-plane migration."""

from __future__ import annotations

import ast
import json
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    """One repository architecture boundary violation."""

    path: str
    line: int
    code: str
    message: str


_ALLOWED_PUBLIC_TOOLS = frozenset({"mc_connection", "mc_operate_bot"})
_DIRECT_RUNTIME_METHODS = frozenset({"execute_action"})
_DIRECT_BRIDGE_METHODS = frozenset({"send_command"})
_ALLOWED_BRIDGE_PATHS = frozenset(
    {
        "src/animetta/tools/minecraft/core/bridge.py",
        "src/animetta/tools/minecraft/core/adapter.py",
    }
)
_ALLOWED_RUNTIME_PATHS = frozenset(
    {
        "src/animetta/tools/minecraft/voyager/command_executor.py",
    }
)
_CANONICAL_SCHEDULER_PATH = "src/animetta/tools/minecraft/voyager/scheduler.py"
_CANONICAL_EXECUTOR_PATH = "src/animetta/tools/minecraft/voyager/command_executor.py"
_REPOSITORY_CLI_BRIDGE_PATH = "src/animetta/tools/minecraft/core/bridge.py"
_MC_MCP_SERVICE_PATH = "services/mc-mcp"
_MC_MCP_PACKAGE_PATH = f"{_MC_MCP_SERVICE_PATH}/package.json"
_MC_MCP_CONTRACT_COPY_PATH = f"{_MC_MCP_SERVICE_PATH}/contracts/gamebot/v2"
_DOMAIN_PATH_PARTS = frozenset({"discovery", "skill", "survival", "tech_tree"})
_FORBIDDEN_DOMAIN_IMPORTS = (
    "animetta.tools.minecraft.core.adapter",
    "animetta.tools.minecraft.core.bridge",
    "animetta.tools.minecraft.voyager.command_executor",
    "animetta.tools.minecraft.voyager.control_plane",
    "animetta.tools.minecraft.voyager.gateway",
    "animetta.tools.minecraft.voyager.scheduler",
)
_FORBIDDEN_RUNTIME_COUPLING = (
    "MinecraftBridge",
    "MinecraftReviewServerLease",
    "MinecraftRuntimeConfig",
    "resolve_external_runtime_dir",
    "runtime_path",
    "voyager-mc-bot",
)
_ROOT_COMPOSE_RUNTIME_MARKERS = (
    "mc-mcp",
    "mineflayer",
    "minecraft-server",
    "services/mc-mcp",
    "src/mcp/cli.js",
)
_PROCESS_SPAWN_METHODS = frozenset(
    {
        "create_subprocess_exec",
        "create_subprocess_shell",
        "Popen",
        "check_call",
        "check_output",
    }
)


def _attribute_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _is_tool_decorator(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):
        node = node.func
    return _attribute_name(node) == "tool"


def _string_literal(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _is_process_spawn_call(node: ast.expr) -> bool:
    if not isinstance(node, ast.Attribute):
        return False
    if node.attr in _PROCESS_SPAWN_METHODS:
        return True
    if not isinstance(node.value, ast.Name):
        return False
    if node.value.id == "subprocess" and node.attr in {"call", "run"}:
        return True
    return node.value.id == "os" and (node.attr == "system" or node.attr.startswith("spawn"))


class _AuditVisitor(ast.NodeVisitor):
    def __init__(self, path: PurePosixPath) -> None:
        self.path = path
        self.violations: list[ArchitectureViolation] = []
        self._classes: list[str] = []

    def _report(self, node: ast.AST, code: str, message: str) -> None:
        self.violations.append(
            ArchitectureViolation(
                path=self.path.as_posix(),
                line=getattr(node, "lineno", 1),
                code=code,
                message=message,
            )
        )

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        path = self.path.as_posix()
        if node.name == "VoyagerCommandScheduler" and path != _CANONICAL_SCHEDULER_PATH:
            self._report(
                node,
                "DUPLICATE_GAMEPLAY_SCHEDULER",
                "gameplay scheduling must remain owned by voyager/scheduler.py",
            )
        if node.name == "CommandExecutor" and path != _CANONICAL_EXECUTOR_PATH:
            self._report(
                node,
                "DUPLICATE_COMMAND_EXECUTOR",
                "state-changing execution must remain owned by voyager/command_executor.py",
            )
        self._classes.append(node.name)
        self.generic_visit(node)
        self._classes.pop()

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_domain_import(alias.name, node)
            self._check_mineflayer_import(alias.name, node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            self._check_domain_import(node.module, node)
            self._check_mineflayer_import(node.module, node)
        self.generic_visit(node)

    def _check_mineflayer_import(self, module: str, node: ast.AST) -> None:
        if "mineflayer" in module.casefold():
            self._report(
                node,
                "ANIMA_MINEFLAYER_OWNERSHIP",
                "Mineflayer dependencies belong only to services/mc-mcp",
            )

    def _check_domain_import(self, module: str, node: ast.AST) -> None:
        parts = set(self.path.parts)
        if not parts.intersection(_DOMAIN_PATH_PARTS):
            return
        if module.startswith(_FORBIDDEN_DOMAIN_IMPORTS):
            self._report(
                node,
                "DOMAIN_CONTROL_PLANE_IMPORT",
                "Minecraft domains must depend on protocols, not control-plane implementations",
            )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._check_config_field(node.target, node)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_config_field(target, node)
        self.generic_visit(node)

    def _check_config_field(self, target: ast.expr, node: ast.AST) -> None:
        if not self._classes or self._classes[-1] != "MinecraftConfig":
            return
        name = _attribute_name(target)
        if name == "mode":
            self._report(
                node,
                "LEGACY_MODE_CONFIG",
                "MinecraftConfig must not own a default Voyager mode",
            )
        elif name == "autonomous":
            self._report(
                node,
                "LEGACY_AUTONOMOUS_CONFIG",
                "MinecraftConfig must not expose the removed autonomous owner",
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_public_tool(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_public_tool(node)
        self.generic_visit(node)

    def _check_public_tool(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.path.as_posix() != "src/animetta/tools/minecraft/core/tools.py":
            return
        if not node.name.startswith("mc_"):
            return
        if not any(_is_tool_decorator(decorator) for decorator in node.decorator_list):
            return
        if node.name not in _ALLOWED_PUBLIC_TOOLS:
            self._report(
                node,
                "OLD_PUBLIC_TOOL",
                f"public Minecraft tool {node.name!r} must migrate to the two-capability gateway",
            )

    def visit_Call(self, node: ast.Call) -> None:
        name = _attribute_name(node.func)
        path = self.path.as_posix()
        if _is_process_spawn_call(node.func) and path != _REPOSITORY_CLI_BRIDGE_PATH:
            self._report(
                node,
                "MC_MCP_PROCESS_OWNERSHIP",
                "Minecraft subprocess bootstrap is allowed only in minecraft/core/bridge.py",
            )
        if name in _DIRECT_BRIDGE_METHODS and path not in _ALLOWED_BRIDGE_PATHS:
            self._report(
                node,
                "DIRECT_GAMEPLAY_CALL",
                f"{name} is outside the adapter/command-executor boundary",
            )
        if name in _DIRECT_RUNTIME_METHODS and path not in _ALLOWED_RUNTIME_PATHS:
            self._report(
                node,
                "DIRECT_GAMEPLAY_CALL",
                f"{name} is outside the command-executor boundary",
            )
        if name == "eval_skill":
            self._report(
                node,
                "PRODUCTION_EVAL_SKILL",
                "production arbitrary skill execution must be removed",
            )
        if name in {"create_task", "ensure_future"} and "/voyager/strategies/" in path:
            self._report(
                node,
                "STRATEGY_BACKGROUND_TASK",
                "Voyager strategies must not create background execution tasks",
            )
        if name in _DIRECT_BRIDGE_METHODS and node.args:
            action = _string_literal(node.args[0])
            if action in {"eval_code", "eval_skill"}:
                self._report(
                    node,
                    "LEGACY_CODE_BODY",
                    "legacy executable skill bodies are not production capabilities",
                )
        if name == "get" and node.args and _string_literal(node.args[0]) == "code":
            owner = node.func.value if isinstance(node.func, ast.Attribute) else None
            if isinstance(owner, ast.Attribute) and owner.attr == "body":
                self._report(
                    node,
                    "LEGACY_CODE_BODY",
                    "legacy skill body code must not drive production execution",
                )
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if (
            isinstance(node.value, str)
            and ("cli.js" in node.value or "services/mc-mcp" in node.value)
            and self.path.as_posix() != _REPOSITORY_CLI_BRIDGE_PATH
        ):
            self._report(
                node,
                "MC_MCP_CLI_BOOTSTRAP_OUTSIDE_BRIDGE",
                "repo-local mc-mcp CLI resolution is allowed only in minecraft/core/bridge.py",
            )
        self.generic_visit(node)


def audit_source(path: PurePosixPath, source: str) -> tuple[ArchitectureViolation, ...]:
    """Audit one Python source file without importing or executing it."""

    tree = ast.parse(source, filename=path.as_posix())
    visitor = _AuditVisitor(path)
    visitor.visit(tree)
    violations = list(visitor.violations)
    if path.as_posix() == "src/animetta/tools/minecraft/core/tools.py":
        public_tools = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("mc_")
            and any(_is_tool_decorator(decorator) for decorator in node.decorator_list)
        }
        if public_tools != _ALLOWED_PUBLIC_TOOLS:
            violations.append(
                ArchitectureViolation(
                    path=path.as_posix(),
                    line=1,
                    code="PUBLIC_TOOL_SURFACE_MISMATCH",
                    message=(
                        "public Minecraft tools must be exactly "
                        f"{sorted(_ALLOWED_PUBLIC_TOOLS)!r}; found {sorted(public_tools)!r}"
                    ),
                )
            )
    if path.as_posix() == "src/animetta/tools/minecraft/voyager/tech_graph.py":
        violations.append(
            ArchitectureViolation(
                path=path.as_posix(),
                line=1,
                code="DUPLICATE_TECH_GRAPH_OWNER",
                message="canonical technology graph must live under minecraft/tech_tree",
            )
        )
    return tuple(sorted(violations, key=lambda item: (item.path, item.line, item.code)))


def audit_repository(root: Path) -> tuple[ArchitectureViolation, ...]:
    """Audit production Minecraft Python sources under ``root``."""

    source_root = root / "src" / "animetta" / "tools" / "minecraft"
    violations: list[ArchitectureViolation] = []
    for disk_path in sorted(source_root.rglob("*.py")):
        relative = PurePosixPath(disk_path.relative_to(root).as_posix())
        violations.extend(audit_source(relative, disk_path.read_text(encoding="utf-8")))
    base_tools_path = root / "src" / "animetta" / "tools" / "base.py"
    if base_tools_path.is_file():
        relative = PurePosixPath(base_tools_path.relative_to(root).as_posix())
        violations.extend(audit_source(relative, base_tools_path.read_text(encoding="utf-8")))
    coupling_paths = (
        root / "src" / "animetta" / "acceptance" / "minecraft_gameplay_review.py",
        root / "config" / "tools.yaml",
        *sorted((root / "scripts").glob("minecraft_*.py")),
        root / "scripts" / "voyager_real_e2e.py",
    )
    for disk_path in coupling_paths:
        if not disk_path.is_file():
            continue
        relative_path = disk_path.relative_to(root).as_posix()
        for line_number, line in enumerate(
            disk_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            token = next(
                (item for item in _FORBIDDEN_RUNTIME_COUPLING if item in line),
                None,
            )
            if token is not None:
                violations.append(
                    ArchitectureViolation(
                        path=relative_path,
                        line=line_number,
                        code="ANIMA_MC_RUNTIME_COUPLING",
                        message=f"Anima must reach Minecraft runtime only through mc-mcp: {token}",
                    )
                )
    violations.extend(_audit_mc_mcp_service(root))
    violations.extend(_audit_root_compose_ownership(root))
    return tuple(sorted(violations, key=lambda item: (item.path, item.line, item.code)))


def _audit_mc_mcp_service(root: Path) -> list[ArchitectureViolation]:
    service_root = root / _MC_MCP_SERVICE_PATH
    package_path = root / _MC_MCP_PACKAGE_PATH
    if not service_root.is_dir() or not package_path.is_file():
        return [
            ArchitectureViolation(
                path=_MC_MCP_PACKAGE_PATH,
                line=1,
                code="MC_MCP_SERVICE_MISSING",
                message="the repository-owned Node service must live at services/mc-mcp",
            )
        ]

    violations: list[ArchitectureViolation] = []
    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [
            ArchitectureViolation(
                path=_MC_MCP_PACKAGE_PATH,
                line=1,
                code="MC_MCP_PACKAGE_INVALID",
                message=f"mc-mcp package.json must be readable JSON: {exc}",
            )
        ]

    binary = package.get("bin") if isinstance(package, dict) else None
    dependencies = package.get("dependencies") if isinstance(package, dict) else None
    scripts = package.get("scripts") if isinstance(package, dict) else None
    package_expectations = (
        (
            isinstance(binary, dict) and binary.get("mc-mcp") == "src/mcp/cli.js",
            "MC_MCP_CLI_CONTRACT",
            "package bin.mc-mcp must resolve to src/mcp/cli.js",
        ),
        (
            isinstance(dependencies, dict) and "mineflayer" in dependencies,
            "MC_MCP_MINEFLAYER_CONTRACT",
            "Mineflayer must be owned as a services/mc-mcp dependency",
        ),
        (
            isinstance(scripts, dict) and {"check", "test"}.issubset(scripts),
            "MC_MCP_QUALITY_CONTRACT",
            "mc-mcp package scripts must expose check and test",
        ),
    )
    for satisfied, code, message in package_expectations:
        if not satisfied:
            violations.append(
                ArchitectureViolation(
                    path=_MC_MCP_PACKAGE_PATH,
                    line=1,
                    code=code,
                    message=message,
                )
            )

    duplicate_contract = root / _MC_MCP_CONTRACT_COPY_PATH
    if duplicate_contract.is_dir() and any(
        candidate.is_file() for candidate in duplicate_contract.rglob("*")
    ):
        violations.append(
            ArchitectureViolation(
                path=_MC_MCP_CONTRACT_COPY_PATH,
                line=1,
                code="DUPLICATE_GAMEBOT_CONTRACT_COPY",
                message="services/mc-mcp must read contracts/gamebot/v2 from the repository root",
            )
        )

    for current_root, directories, filenames in os.walk(service_root):
        directories[:] = [
            name for name in directories if name not in {"node_modules", ".git", ".cache"}
        ]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            python_path = Path(current_root) / filename
            violations.append(
                ArchitectureViolation(
                    path=python_path.relative_to(root).as_posix(),
                    line=1,
                    code="MC_MCP_PYTHON_RUNTIME",
                    message="services/mc-mcp is an independently owned Node.js runtime",
                )
            )
    return violations


def _audit_root_compose_ownership(root: Path) -> list[ArchitectureViolation]:
    violations: list[ArchitectureViolation] = []
    compose_paths = sorted((*root.glob("docker-compose*.yml"), *root.glob("docker-compose*.yaml")))
    for compose_path in compose_paths:
        try:
            content = compose_path.read_text(encoding="utf-8")
            document = yaml.safe_load(content)
        except (OSError, UnicodeError, yaml.YAMLError):
            continue
        services = document.get("services") if isinstance(document, dict) else None
        if not isinstance(services, dict):
            continue
        for service_name, service in services.items():
            serialized = json.dumps(service, ensure_ascii=True, sort_keys=True).casefold()
            candidate = f"{service_name} {serialized}".casefold()
            marker = next(
                (item for item in _ROOT_COMPOSE_RUNTIME_MARKERS if item in candidate),
                None,
            )
            if marker is None:
                continue
            line = next(
                (
                    number
                    for number, source_line in enumerate(content.splitlines(), start=1)
                    if str(service_name) in source_line or marker in source_line.casefold()
                ),
                1,
            )
            violations.append(
                ArchitectureViolation(
                    path=compose_path.relative_to(root).as_posix(),
                    line=line,
                    code="ANIMA_MC_COMPOSE_OWNERSHIP",
                    message=(
                        "root Compose must not own mc-mcp, Mineflayer, or Minecraft runtime; "
                        f"found {marker!r}"
                    ),
                )
            )
    return violations


def render_report(violations: tuple[ArchitectureViolation, ...]) -> str:
    """Render stable, reviewable report output."""

    if not violations:
        return "Minecraft architecture audit: no violations"
    lines = [f"Minecraft architecture audit: {len(violations)} violation(s)"]
    lines.extend(f"{item.path}:{item.line}: [{item.code}] {item.message}" for item in violations)
    return "\n".join(lines)
