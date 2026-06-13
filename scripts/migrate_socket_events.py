#!/usr/bin/env python3
"""
Socket.IO Event Name Migration Script
======================================
Migrates all Socket.IO event names to domain:action colon-separated convention.

Handles three targets:
  1. config/socket-events.json -- dot->colon in all "name" fields
  2. Backend .py files -- .emit()/.on() + routes.py .get("name","fallback") patterns
  3. Frontend .ts/.vue files -- socket.emit()/socket.on() calls

Usage:
    # Dry-run (preview changes only)
    python scripts/migrate_socket_events.py --dry-run

    # Execute migration
    python scripts/migrate_socket_events.py
"""

import json
import re
import sys
import argparse
from pathlib import Path

# ==========================================================
# EVENT MAPPING: old_name -> new_name
# ==========================================================

EVENT_MAPPING: dict[str, str] = {
    # -- Lifecycle (outbound flat names) --
    "heartbeat":                "lifecycle:heartbeat",
    "heartbeat-ack":            "lifecycle:heartbeat_ack",
    "connection-established":   "lifecycle:connection_established",

    # -- Chat (outbound flat names) --
    "text_input":               "chat:text_input",
    "raw_audio_data":           "chat:raw_audio_data",
    "mic_audio_end":            "chat:mic_audio_end",
    "interrupt_signal":         "chat:interrupt_signal",
    "sentence":                 "chat:sentence",
    "transcript":               "chat:transcript",
    "expression":               "chat:expression",
    "stop_audio":               "chat:stop_audio",
    "audio_with_expression":    "chat:audio_with_expression",
    "model_status":             "chat:model_status",

    # -- History (outbound flat names) --
    "fetch_history_list":       "history:fetch_list",
    "fetch_history":            "history:fetch",
    "clear_history":            "history:clear",
    "create_new_history":       "history:create",
    "history-data":             "history:data",
    "history-cleared":          "history:cleared",
    "new-history-created":      "history:created",

    # -- Config (outbound flat names) --
    "switch_config":            "config:switch",
    "set_log_level":            "config:set_log_level",
    "get_config":               "config:get",
    "config_data":              "config:data",
    "config-switched":          "config:switched",
    "log_level_changed":        "config:log_level_changed",

    # -- Persona (outbound flat names) --
    "get_available_personas":   "persona:list",
    "set_persona":              "persona:set",
    "set_personality_mode":     "persona:set_personality_mode",
    "persona_updated":          "persona:updated",
    "personality_updated":      "persona:personality_updated",

    # -- Desktop (outbound flat names) --
    "desktop_register":         "desktop:register",
    "desktop_live2d_action":    "desktop:live2d_action",
    "desktop_chat_message":     "desktop:chat_message",
    "desktop_voice_start":      "desktop:voice_start",
    "desktop_voice_stop":       "desktop:voice_stop",
    "desktop.registered":       "desktop:registered",
    "desktop.action_queued":    "desktop:action_queued",

    # -- Bilibili --
    "bilibili.connect":         "bilibili:connect",
    "bilibili.disconnect":      "bilibili:disconnect",
    "bilibili.update_room":     "bilibili:update_room",
    "danmaku":                  "bilibili:danmaku",
    "danmaku.status":           "bilibili:danmaku_status",
    "danmaku.ai_reply":         "bilibili:ai_reply",

    # -- Minecraft --
    "minecraft.start":          "minecraft:start",
    "minecraft.stop":           "minecraft:stop",
    "minecraft.status":         "minecraft:status",

    # -- Translation --
    "translation.configure":    "translation:configure",
    "translation.status":       "translation:status",
    "subtitle.translation":     "translation:subtitle",

    # -- Memory --
    "memory_organize":          "memory:organize",
    "get_wiki_pages":           "memory:get_wiki",
    "memory.organize.progress": "memory:organize_progress",
    "memory.organize.result":   "memory:organize_result",

    # -- Meme --
    "meme_add":                 "meme:add",

    # -- Live2D --
    "live2d.action":            "live2d:action",

    # -- System (unified) --
    "control":                  "system:control",
    "error":                    "system:error",

    # NOTE: Already conforming -- NOT included (left as-is):
    #   sing:process, sing:confirm_lyrics, sing:cancel, sing:subtitle_sync,
    #   sing:progress, sing:complete, sing:error, sing:lyrics_ready,
    #   sing:subtitle_line, meme:list, meme:review, meme:dataset
    #
    # NOTE: Socket.IO reserved -- NOT renamed:
    #   connect, disconnect
}


def _load_json_name_mappings() -> dict[str, str]:
    """
    Auto-generate dot->colon mappings from config/socket-events.json.
    Every "name": "domain.action" becomes "domain.action" -> "domain:action".
    Manual EVENT_MAPPING entries take precedence (for special domain remapping).
    """
    project_root = Path(__file__).resolve().parent.parent
    json_path = project_root / "config" / "socket-events.json"
    mappings: dict[str, str] = {}
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        for domain, events in data.items():
            if not isinstance(events, dict):
                continue
            for _event_key, event_def in events.items():
                if not isinstance(event_def, dict):
                    continue
                old_name = event_def.get("name", "")
                if "." in old_name and ":" not in old_name:
                    new_name = old_name.replace(".", ":", 1)
                    mappings[old_name] = new_name
    except Exception:
        pass
    return mappings


# Auto-generated dot->colon mappings from JSON config
JSON_MAPPINGS = _load_json_name_mappings()

# Merged: manual EVENT_MAPPING takes precedence over auto-generated
ALL_MAPPINGS: dict[str, str] = {**JSON_MAPPINGS, **EVENT_MAPPING}


# ==========================================================
# FILE PATHS
# ==========================================================

BACKEND_DIR = Path("src/animetta")
FRONTEND_DIR = Path("frontend/src")
JSON_CONFIG_REL = Path("config/socket-events.json")

BACKEND_GLOBS = ["**/*.py"]
FRONTEND_GLOBS = ["**/*.ts", "**/*.vue"]


# ==========================================================
# REGEX PATTERNS
# ==========================================================

def build_patterns(old_name: str) -> list[tuple[re.Pattern, str]]:
    """
    Build regex patterns that match `old_name` only when used as an
    event name in Socket.IO contexts.

    Returns list of (compiled_regex, replacement_template) pairs.
    """
    escaped = re.escape(old_name)
    new_name = ALL_MAPPINGS[old_name]
    q = r'["\']'   # match either " or '
    s = r'\s*'     # optional whitespace (handles multi-line)

    patterns: list[tuple[re.Pattern, str]] = []

    # Pattern 1: .emit('old_name'  or  .on('old_name'
    p1 = re.compile(
        r'(\.(?:emit|on)\(' + s + q + r')' + escaped + r'(' + q + r')'
    )
    patterns.append((p1, r'\1' + new_name + r'\2'))

    # Pattern 2: broadcast_to_desktop_clients(x, 'old_name'
    p2 = re.compile(
        r'(broadcast_to_desktop_clients\([^,]+,' + s + q + r')' + escaped + r'(' + q + r')'
    )
    patterns.append((p2, r'\1' + new_name + r'\2'))

    # Pattern 3: .get("name", "old_name") -- routes.py fallback strings
    p3 = re.compile(
        r'(\.get\(' + s + q + r'name' + q + s + r',' + s + q + r')' + escaped + r'(' + q + r')'
    )
    patterns.append((p3, r'\1' + new_name + r'\2'))

    return patterns


# ==========================================================
# MIGRATION LOGIC
# ==========================================================

def find_files(base: Path, globs: list[str]) -> list[Path]:
    """Find all files matching the glob patterns."""
    files: list[Path] = []
    for g in globs:
        files.extend(base.glob(g))
    return sorted(set(files))



def migrate_source_file(filepath: Path, dry_run: bool = False) -> int:
    """Migrate event names in a single source file. Returns count of replacements."""
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [SKIP] {filepath}: {e}")
        return 0

    original = content
    total_replacements = 0

    for old_name, new_name in ALL_MAPPINGS.items():
        for pattern, replacement in build_patterns(old_name):
            new_content, n = pattern.subn(replacement, content)
            if n > 0:
                total_replacements += n
                content = new_content

    if total_replacements == 0:
        return 0

    rel = filepath.relative_to(Path.cwd()) if filepath.is_absolute() else filepath
    if dry_run:
        print(f"  [DRY-RUN] {rel}: {total_replacements} replacement(s)")
    else:
        filepath.write_text(content, encoding="utf-8")
        print(f"  [OK] {rel}: {total_replacements} replacement(s)")

    return total_replacements


def migrate_json_config(filepath: Path, dry_run: bool = False) -> int:
    """
    Migrate the JSON config file: replace dot with colon in all 'name' fields.

    This is JSON-aware (preserves formatting, indentation, key order).
    """
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  [SKIP] {filepath}: {e}")
        return 0

    total_replacements = 0

    def _walk(obj):
        nonlocal total_replacements
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key == "name" and isinstance(val, str):
                    if "." in val and ":" not in val:
                        old_val = val
                        new_val = val.replace(".", ":", 1)
                        obj[key] = new_val
                        total_replacements += 1
                        if dry_run:
                            print(f"    {old_val} -> {new_val}")
                else:
                    _walk(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(data)

    if total_replacements == 0:
        return 0

    rel = filepath.relative_to(Path.cwd()) if filepath.is_absolute() else filepath
    if dry_run:
        print(f"  [DRY-RUN] {rel}: {total_replacements} name field(s)")
    else:
        filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"  [OK] {rel}: {total_replacements} name field(s)")

    return total_replacements


def main():
    parser = argparse.ArgumentParser(
        description="Migrate Socket.IO event names to domain:action convention"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    backend_dir = project_root / "src" / "animetta"
    frontend_dir = project_root / "frontend" / "src"
    json_config = project_root / "config" / "socket-events.json"

    dry_run = args.dry_run
    mode_label = "DRY-RUN" if dry_run else "EXECUTE"

    print("=" * 60)
    print(f" Socket.IO Event Name Migration  [{mode_label}]")
    print("=" * 60)
    print(f" Event mappings loaded: {len(ALL_MAPPINGS)}")
    print(f"   (JSON auto-generated: {len(JSON_MAPPINGS)}, "
          f"manual: {len(EVENT_MAPPING)})")
    print()

    total_files_changed = 0
    total_replacements = 0

    # --- Phase 1: JSON Config ---
    print("[1/3] Migrating JSON config...")
    if json_config.exists():
        n = migrate_json_config(json_config, dry_run=dry_run)
        if n > 0:
            total_files_changed += 1
            total_replacements += n
    else:
        print(f"  [SKIP] {json_config} not found")
    print()

    # --- Phase 2: Backend .py files ---
    print("[2/3] Migrating backend Python files...")
    backend_files = find_files(backend_dir, BACKEND_GLOBS)
    for f in backend_files:
        n = migrate_source_file(f, dry_run=dry_run)
        if n > 0:
            total_files_changed += 1
            total_replacements += n
    print()

    # --- Phase 3: Frontend .ts/.vue files ---
    print("[3/3] Migrating frontend TypeScript/Vue files...")
    frontend_files = find_files(frontend_dir, FRONTEND_GLOBS)
    for f in frontend_files:
        n = migrate_source_file(f, dry_run=dry_run)
        if n > 0:
            total_files_changed += 1
            total_replacements += n
    print()

    # --- Summary ---
    print("=" * 60)
    print(f" Migration complete: {total_files_changed} file(s) changed, "
          f"{total_replacements} replacement(s)")
    if dry_run:
        print(" (Dry-run mode -- no files were modified)")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
