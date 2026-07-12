#!/usr/bin/env python3
"""
Validate Socket.IO event name consistency between config/socket-events.json
and the codebase (Python backend + TypeScript frontend).

Called during Docker build to block deployment if events are out of sync.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_JSON = ROOT / "config" / "socket-events.json"
TS_FILE = ROOT / "frontend" / "src" / "constants" / "socket-events.ts"
FRONTEND_SRC_DIR = ROOT / "frontend" / "src"
FRONTEND_ENTRY_FILES = [
    ROOT / "frontend" / "live.html",
    ROOT / "frontend" / "public" / "live.html",
]
SRC_DIR = ROOT / "src" / "animetta"
PYTHON_EVENT_DIRS = [
    SRC_DIR,
    ROOT / "scripts",
    ROOT / "tests",
]
BUILTIN_SOCKET_EVENTS = {"*", "connect", "disconnect", "connect_error", "error"}
LEGACY_ADAPTER_FILES = {
    SRC_DIR / "orchestration" / "server" / "routes.py",
    SRC_DIR / "orchestration" / "chat_delivery.py",
}


def load_events() -> dict[str, str]:
    """Load all event names from socket-events.json as {key: name}."""
    with open(EVENTS_JSON, encoding="utf-8") as f:
        data = json.load(f)

    events = {}
    for module, actions in data.items():
        for action, config in actions.items():
            if isinstance(config, dict) and "name" in config:
                key = f"{module}.{action}"
                events[key] = config["name"]
    return events


def load_aliases() -> set[str]:
    """Load declared legacy aliases; aliases are not ordinary event names."""
    with open(EVENTS_JSON, encoding="utf-8") as f:
        data = json.load(f)
    return {
        alias
        for actions in data.values()
        for definition in actions.values()
        if isinstance(definition, dict)
        for alias in definition.get("aliases", [])
        if isinstance(alias, str) and alias
    }


def validate_legacy_alias_boundaries(aliases: set[str]) -> list[str]:
    """Reject direct legacy Socket.IO calls outside the declared adapters."""
    errors: list[str] = []
    call_pattern = re.compile(
        r'(?:@)?(?:sio|socket|sock|client)(?:\.value)?\.(?:emit|on|off|once)\(\s*["\']([^"\']+)["\']'
    )
    source_files = list(SRC_DIR.rglob("*.py")) if SRC_DIR.exists() else []
    if FRONTEND_SRC_DIR.exists():
        source_files.extend(
            path for path in FRONTEND_SRC_DIR.rglob("*") if path.suffix in {".ts", ".vue"}
        )
    allowed = {path.resolve() for path in LEGACY_ADAPTER_FILES}
    for source_file in source_files:
        if source_file.resolve() in allowed:
            continue
        content = source_file.read_text(encoding="utf-8", errors="ignore")
        for match in call_pattern.finditer(content):
            if match.group(1) in aliases:
                rel = source_file.relative_to(ROOT).as_posix()
                errors.append(
                    f"{rel}: legacy event '{match.group(1)}' is outside the adapter boundary"
                )
    return errors


def validate_json_structure(events: dict[str, str]) -> list[str]:
    """Validate all events follow module:action format."""
    errors = []
    for key, name in events.items():
        if ":" not in name:
            errors.append(f"Event '{key}' -> '{name}' missing ':' separator")
        parts = name.split(":")
        if len(parts) != 2:
            errors.append(f"Event '{key}' -> '{name}' should have exactly one ':'")
        if not parts[0] or not parts[1]:
            errors.append(f"Event '{key}' -> '{name}' has empty module or action")
    return errors


def validate_ts_file(events: dict[str, str]) -> list[str]:
    """Validate TypeScript file references all events from JSON."""
    if not TS_FILE.exists():
        return [f"TypeScript file missing: {TS_FILE}"]

    ts_content = TS_FILE.read_text(encoding="utf-8")
    errors = []

    for key, name in events.items():
        module, action = key.split(".")
        # Check that the TS file references this event via socketEvents.{module}.{action}.name
        ts_ref = f"socketEvents.{module}.{action}.name"
        if ts_ref not in ts_content:
            errors.append(f"TS file missing reference to '{key}' (expected '{ts_ref}')")

    return errors


def validate_frontend_event_literals(events: dict[str, str]) -> list[str]:
    """Check frontend socket event literals use event names from the JSON."""
    if not FRONTEND_SRC_DIR.exists() and not any(
        path.exists() for path in FRONTEND_ENTRY_FILES
    ):
        return []

    event_names = set(events.values())
    errors = []
    call_pattern = re.compile(
        r'\b(?:socket|sock)(?:\.value)?\.(emit|on|off|once)\(\s*["\']([^"\']+)["\']'
    )

    source_files = list(FRONTEND_SRC_DIR.rglob("*")) if FRONTEND_SRC_DIR.exists() else []
    source_files.extend(
        path
        for path in FRONTEND_ENTRY_FILES
        if path.exists() and path.is_relative_to(ROOT)
    )

    for source_file in source_files:
        if source_file.suffix not in {".ts", ".vue", ".html"}:
            continue
        if source_file.resolve() == TS_FILE.resolve():
            continue
        content = source_file.read_text(encoding="utf-8", errors="ignore")
        for match in call_pattern.finditer(content):
            operation = match.group(1)
            event_name = match.group(2)
            if event_name.startswith("{") or event_name.startswith("$"):
                continue
            if event_name in BUILTIN_SOCKET_EVENTS:
                continue
            if event_name not in event_names:
                rel = source_file.relative_to(ROOT).as_posix()
                errors.append(
                    f"{rel}: {operation}('{event_name}') not in socket-events.json"
                )

    return errors


def validate_python_emits(events: dict[str, str]) -> list[str]:
    """Check that Python socket event literals use event names from the JSON."""
    event_names = set(events.values())
    errors = []

    # Patterns:
    #   sio.emit("event_name", ...)
    #   client.on("event_name", ...)
    #   @sio.on("event_name")
    call_pattern = re.compile(
        r'(?:await\s+)?(?:sio|socket|client)\.(emit|on|off|once)\(\s*["\']([^"\']+)["\']'
    )
    decorator_pattern = re.compile(
        r'@(?:sio|socket|client)\.on\(\s*["\']([^"\']+)["\']'
    )

    for event_dir in PYTHON_EVENT_DIRS:
        if not event_dir.exists():
            continue
        for py_file in event_dir.rglob("*.py"):
            if py_file.resolve() == Path(__file__).resolve():
                continue
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            for match in call_pattern.finditer(content):
                operation = match.group(1)
                event_name = match.group(2)
                if event_name.startswith("{") or event_name.startswith("$"):
                    continue
                if event_name in BUILTIN_SOCKET_EVENTS:
                    continue
                if event_name not in event_names:
                    rel = py_file.relative_to(ROOT).as_posix()
                    errors.append(
                        f"{rel}: {operation}('{event_name}') not in socket-events.json"
                    )
            for match in decorator_pattern.finditer(content):
                event_name = match.group(1)
                if event_name.startswith("{") or event_name.startswith("$"):
                    continue
                if event_name in BUILTIN_SOCKET_EVENTS:
                    continue
                if event_name not in event_names:
                    rel = py_file.relative_to(ROOT).as_posix()
                    errors.append(
                        f"{rel}: on('{event_name}') not in socket-events.json"
                    )

    return errors


def main() -> int:
    print(f"Validating Socket.IO events from {EVENTS_JSON}")

    if not EVENTS_JSON.exists():
        print(f"ERROR: {EVENTS_JSON} not found")
        return 1

    events = load_events()
    aliases = load_aliases()
    print(f"  Found {len(events)} event definitions")

    all_errors: list[str] = []

    # 1. Validate JSON structure
    struct_errors = validate_json_structure(events)
    all_errors.extend(struct_errors)
    if struct_errors:
        print(f"  [FAIL] {len(struct_errors)} structure errors")
    else:
        print("  [OK] All events follow module:action format")

    # 2. Validate TypeScript file (skip if not present, e.g. in minimal Docker)
    if TS_FILE.exists():
        ts_errors = validate_ts_file(events)
        all_errors.extend(ts_errors)
        if ts_errors:
            print(f"  [FAIL] {len(ts_errors)} TypeScript mismatches")
        else:
            print("  [OK] TypeScript file references all events")
    else:
        print("  [SKIP] TypeScript file not found (skipping TS validation)")

    if FRONTEND_SRC_DIR.exists():
        frontend_errors = validate_frontend_event_literals(events)
        all_errors.extend(frontend_errors)
        if frontend_errors:
            print(f"  [FAIL] {len(frontend_errors)} frontend event mismatches")
            for err in frontend_errors:
                print(f"    - {err}")
        else:
            print("  [OK] All frontend socket event literals use valid event names")

    # 3. Validate Python socket event literals
    if any(path.exists() for path in PYTHON_EVENT_DIRS):
        py_errors = validate_python_emits(events)
        all_errors.extend(py_errors)
        if py_errors:
            print(f"  [FAIL] {len(py_errors)} Python event mismatches")
            for err in py_errors:
                print(f"    - {err}")
        else:
            print("  [OK] All Python socket event literals use valid event names")

    alias_errors = validate_legacy_alias_boundaries(aliases)
    all_errors.extend(alias_errors)
    if alias_errors:
        print(f"  [FAIL] {len(alias_errors)} legacy alias boundary violations")
        for err in alias_errors:
            print(f"    - {err}")
    else:
        print("  [OK] Legacy aliases are confined to declared adapters")

    if all_errors:
        print(f"\nFAILED: {len(all_errors)} validation errors")
        return 1

    print("\nPASSED: All event validations passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
