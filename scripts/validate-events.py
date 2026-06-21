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
SRC_DIR = ROOT / "src" / "animetta"


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


def validate_python_emits(events: dict[str, str]) -> list[str]:
    """Check that Python emit calls use event names from the JSON."""
    event_names = set(events.values())
    errors = []

    # Pattern: sio.emit("event_name", ...) or await sio.emit("event_name", ...)
    emit_pattern = re.compile(r'(?:await\s+)?sio\.emit\(\s*["\']([^"\']+)["\']')

    for py_file in SRC_DIR.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        for match in emit_pattern.finditer(content):
            event_name = match.group(1)
            # Skip dynamic event names (variables, f-strings)
            if event_name.startswith("{") or event_name.startswith("$"):
                continue
            # Skip config-loaded events (e.g. events["chat"]["text"]["name"])
            if "events[" in event_name:
                continue
            if event_name not in event_names:
                rel = py_file.relative_to(ROOT)
                errors.append(
                    f"{rel}: emit('{event_name}') not in socket-events.json"
                )

    return errors


def main() -> int:
    print(f"Validating Socket.IO events from {EVENTS_JSON}")

    if not EVENTS_JSON.exists():
        print(f"ERROR: {EVENTS_JSON} not found")
        return 1

    events = load_events()
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

    # 3. Validate Python emits
    if SRC_DIR.exists():
        py_errors = validate_python_emits(events)
        all_errors.extend(py_errors)
        if py_errors:
            print(f"  [FAIL] {len(py_errors)} Python emit mismatches")
            for err in py_errors:
                print(f"    - {err}")
        else:
            print("  [OK] All Python emit calls use valid event names")

    if all_errors:
        print(f"\nFAILED: {len(all_errors)} validation errors")
        return 1

    print("\nPASSED: All event validations passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
