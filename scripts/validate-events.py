#!/usr/bin/env python3
"""
Validate Socket.IO event name consistency.

This script checks:
1. config/socket-events.json is valid JSON with correct structure
2. Frontend uses Events constants (not string literals)
3. Backend uses EVENTS config (not string literals)

Usage:
    python scripts/validate-events.py

Exit codes:
    0 - Validation passed
    1 - Validation failed
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

# Project root directory
ROOT_DIR = Path(__file__).parent.parent

# File paths
JSON_PATH = ROOT_DIR / "config" / "socket-events.json"
ROUTES_PY = ROOT_DIR / "src" / "animetta" / "orchestration" / "server" / "routes.py"
FRONTEND_DIR = ROOT_DIR / "frontend" / "src"


def load_json_events() -> dict[str, str]:
    """Load all event names from JSON file, return {event_name: module_name} mapping."""
    with open(JSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    events = {}
    for module_name, module_events in data.items():
        for event_key, event_config in module_events.items():
            event_name = event_config["name"]
            events[event_name] = module_name

    return events


def check_json_structure() -> list[str]:
    """Validate JSON structure is correct."""
    errors = []

    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        errors.append(f"Invalid JSON: {e}")
        return errors

    # Check each module has events
    for module_name, module_events in data.items():
        if not isinstance(module_events, dict):
            errors.append(f"Module '{module_name}' should be a dict")
            continue

        for event_key, event_config in module_events.items():
            if "name" not in event_config:
                errors.append(f"Event '{module_name}.{event_key}' missing 'name' field")
            if "payload" not in event_config:
                errors.append(f"Event '{module_name}.{event_key}' missing 'payload' field")

    return errors


def check_routes_py_uses_events() -> list[str]:
    """Check that routes.py uses EVENTS config, not string literals."""
    errors = []

    with open(ROUTES_PY, encoding="utf-8") as f:
        content = f.read()

    # Check for old-style string literals (excluding connect/disconnect which are built-in)
    old_pattern = r'sio\.on\(["\'](?!connect|disconnect)([^"\']+)["\']'
    old_matches = re.findall(old_pattern, content)

    if old_matches:
        errors.append(f"routes.py still uses string literals: {old_matches}")

    # Check that EVENTS is imported and used
    if "EVENTS" not in content:
        errors.append("routes.py doesn't import or use EVENTS")

    return errors


def check_frontend_uses_constants() -> list[str]:
    """Check that frontend uses Events constants, not string literals."""
    errors = []

    # Find all .ts and .vue files
    ts_files = list(FRONTEND_DIR.rglob("*.ts"))
    vue_files = list(FRONTEND_DIR.rglob("*.vue"))
    all_files = ts_files + vue_files

    for file_path in all_files:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Skip socket-events.ts itself (it defines the constants)
        if "socket-events.ts" in str(file_path):
            continue

        # Check for old-style string literals in emit/on/once/off calls
        emit_pattern = r'socket\.emit\(["\']([^"\']+)["\']'
        on_pattern = r'socket\.on\(["\']([^"\']+)["\']'
        once_pattern = r'socket\.once\(["\']([^"\']+)["\']'
        off_pattern = r'socket\.off\(["\']([^"\']+)["\']'

        # Also check for sock.emit (aliased socket)
        sock_emit_pattern = r'sock\.emit\(["\']([^"\']+)["\']'
        sock_once_pattern = r'sock\.once\(["\']([^"\']+)["\']'

        all_patterns = [
            (emit_pattern, "emit"),
            (on_pattern, "on"),
            (once_pattern, "once"),
            (off_pattern, "off"),
            (sock_emit_pattern, "emit"),
            (sock_once_pattern, "once"),
        ]

        for pattern, method in all_patterns:
            matches = re.findall(pattern, content)
            # Filter out socket.io built-in events
            builtin_events = {"connect", "disconnect", "connect_error"}
            old_events = [m for m in matches if m not in builtin_events]

            if old_events:
                rel_path = file_path.relative_to(ROOT_DIR)
                errors.append(f"{rel_path}: still uses string literals for {method}: {old_events}")

    return errors


def check_frontend_has_imports() -> list[str]:
    """Check that frontend files import Events constants."""
    errors = []

    # Find all .ts and .vue files that use socket
    ts_files = list(FRONTEND_DIR.rglob("*.ts"))
    vue_files = list(FRONTEND_DIR.rglob("*.vue"))
    all_files = ts_files + vue_files

    for file_path in all_files:
        with open(file_path, encoding="utf-8") as f:
            content = f.read()

        # Skip socket-events.ts itself
        if "socket-events.ts" in str(file_path):
            continue

        # Check if file uses socket.emit/on/once/off
        uses_socket = any(
            pattern in content
            for pattern in [
                "socket.emit(",
                "socket.on(",
                "socket.once(",
                "socket.off(",
                "sock.emit(",
                "sock.once(",
            ]
        )

        if uses_socket:
            # Check if it imports Events
            if "Events" not in content:
                rel_path = file_path.relative_to(ROOT_DIR)
                errors.append(f"{rel_path}: uses socket but doesn't import Events")

    return errors


def main() -> int:
    """Main function."""
    print("=" * 60)
    print("Socket.IO Event Naming Validation")
    print("=" * 60)

    all_errors: list[str] = []

    # 1. Validate JSON structure
    print("\n[1/4] Validating JSON structure...")
    json_errors = check_json_structure()
    if json_errors:
        all_errors.extend(json_errors)
        print(f"  FAIL - Found {len(json_errors)} structural errors")
    else:
        print("  OK - JSON structure is valid")

    # 2. Load JSON events
    print("\n[2/4] Loading JSON events...")
    try:
        json_events = load_json_events()
        print(f"  OK - Loaded {len(json_events)} events")
    except Exception as e:
        print(f"  FAIL - Load failed: {e}")
        return 1

    # 3. Check routes.py uses EVENTS
    print("\n[3/4] Checking routes.py...")
    routes_errors = check_routes_py_uses_events()
    if routes_errors:
        all_errors.extend(routes_errors)
        print(f"  FAIL - Found {len(routes_errors)} issues")
    else:
        print("  OK - routes.py uses EVENTS config")

    # 4. Check frontend uses constants
    print("\n[4/4] Checking frontend...")
    frontend_errors = check_frontend_uses_constants()
    import_errors = check_frontend_has_imports()

    if frontend_errors:
        all_errors.extend(frontend_errors)
        print(f"  FAIL - Found {len(frontend_errors)} string literal issues")

    if import_errors:
        all_errors.extend(import_errors)
        print(f"  FAIL - Found {len(import_errors)} missing imports")

    if not frontend_errors and not import_errors:
        print("  OK - Frontend uses Events constants")

    # Output results
    print("\n" + "=" * 60)
    if all_errors:
        print(f"Validation FAILED: {len(all_errors)} errors found")
        print("=" * 60)
        for i, error in enumerate(all_errors, 1):
            print(f"{i}. {error}")
        print("=" * 60)
        return 1
    else:
        print("Validation PASSED: All event names are consistent")
        print("=" * 60)
        return 0


if __name__ == "__main__":
    sys.exit(main())
