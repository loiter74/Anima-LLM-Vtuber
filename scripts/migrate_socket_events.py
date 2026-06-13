#!/usr/bin/env python3
"""
Socket.IO Event Name Migration Script
======================================
Migrates all Socket.IO event names to domain:action colon-separated convention.

Usage:
    # Dry-run (preview changes only)
    python scripts/migrate_socket_events.py --dry-run

    # Execute migration
    python scripts/migrate_socket_events.py
"""

import re
import sys
import argparse
from pathlib import Path

# ──────────────────────────────────────────────────────────
# EVENT MAPPING: old_name → new_name
# ──────────────────────────────────────────────────────────

EVENT_MAPPING: dict[str, str] = {
    # ── Lifecycle ──
    "heartbeat":           "lifecycle:heartbeat",
    "heartbeat-ack":      "lifecycle:heartbeat_ack",
    "connection-established": "lifecycle:connection_established",

    # ── Chat ──
    "text_input":          "chat:text_input",
    "raw_audio_data":      "chat:raw_audio_data",
    "mic_audio_end":       "chat:mic_audio_end",
    "interrupt_signal":    "chat:interrupt_signal",
    "sentence":            "chat:sentence",
    "transcript":          "chat:transcript",
    "expression":          "chat:expression",
    "stop_audio":          "chat:stop_audio",
    "audio_with_expression": "chat:audio_with_expression",
    "model_status":        "chat:model_status",

    # ── History ──
    "fetch_history_list":  "history:fetch_list",
    "fetch_history":       "history:fetch",
    "clear_history":       "history:clear",
    "create_new_history":  "history:create",
    "history-data":        "history:data",
    "history-cleared":     "history:cleared",
    "new-history-created": "history:created",

    # ── Config ──
    "switch_config":       "config:switch",
    "set_log_level":       "config:set_log_level",
    "get_config":          "config:get",
    "config_data":         "config:data",
    "config-switched":     "config:switched",
    "log_level_changed":   "config:log_level_changed",

    # ── Persona ──
    "get_available_personas":     "persona:list",
    "set_persona":                "persona:set",
    "set_personality_mode":       "persona:set_personality_mode",
    "persona_updated":            "persona:updated",
    "personality_updated":        "persona:personality_updated",

    # ── Desktop ──
    "desktop_register":      "desktop:register",
    "desktop_live2d_action": "desktop:live2d_action",
    "desktop_chat_message":  "desktop:chat_message",
    "desktop_voice_start":   "desktop:voice_start",
    "desktop_voice_stop":    "desktop:voice_stop",
    "desktop.registered":    "desktop:registered",
    "desktop.action_queued": "desktop:action_queued",

    # ── Bilibili ──
    "bilibili.connect":      "bilibili:connect",
    "bilibili.disconnect":   "bilibili:disconnect",
    "bilibili.update_room":  "bilibili:update_room",
    "danmaku":               "bilibili:danmaku",
    "danmaku.status":        "bilibili:danmaku_status",
    "danmaku.ai_reply":      "bilibili:ai_reply",

    # ── Minecraft ──
    "minecraft.start":       "minecraft:start",
    "minecraft.stop":        "minecraft:stop",
    "minecraft.status":      "minecraft:status",

    # ── Translation ──
    "translation.configure": "translation:configure",
    "translation.status":    "translation:status",
    "subtitle.translation":  "translation:subtitle",

    # ── Memory ──
    "memory_organize":            "memory:organize",
    "get_wiki_pages":             "memory:get_wiki",
    "memory.organize.progress":   "memory:organize_progress",
    "memory.organize.result":     "memory:organize_result",

    # ── Meme ──
    "meme_add":              "meme:add",

    # ── Live2D ──
    "live2d.action":         "live2d:action",

    # ── System (unified) ──
    "control":               "system:control",
    "error":                 "system:error",

    # NOTE: Already conforming — NOT included (left as-is):
    #   sing:process, sing:confirm_lyrics, sing:cancel, sing:subtitle_sync,
    #   sing:progress, sing:complete, sing:error, sing:lyrics_ready,
    #   sing:subtitle_line, meme:list, meme:review, meme:dataset
    #
    # NOTE: Socket.IO reserved — NOT renamed:
    #   connect, disconnect
}

# ──────────────────────────────────────────────────────────
# FILE GLOBS
# ──────────────────────────────────────────────────────────

BACKEND_DIR = Path("src/animetta")
FRONTEND_DIR = Path("frontend/src")

BACKEND_GLOBS = ["**/*.py"]
FRONTEND_GLOBS = ["**/*.ts", "**/*.vue"]

# ──────────────────────────────────────────────────────────
# REGEX PATTERNS
# ──────────────────────────────────────────────────────────

def build_patterns(old_name: str) -> list[tuple[str, str]]:
    """
    Build regex patterns that match `old_name` only when used as an
    event name in Socket.IO emit/on/broadcast contexts.

    Returns list of (compiled_regex, replacement_template) pairs.
    """
    escaped = re.escape(old_name)
    quote = r'["\']'  # match either " or '
    s = r'\s*'         # optional whitespace (handles multi-line)

    patterns = []

    # Pattern 1: .emit('old_name'  or  .on('old_name'
    # Matches: self.sio.emit("danmaku", ...)  /  socket.on("danmaku", ...)
    # Also matches .emit("danmaku") with no other args
    p1 = re.compile(
        r'(\.(?:emit|on)\(' + s + quote + r')' + escaped + r'(' + quote + r')'
    )
    r1 = r'\1' + EVENT_MAPPING[old_name] + r'\2'
    patterns.append((p1, r1))

    # Pattern 2: broadcast_to_desktop_clients(x, 'old_name'
    # Event is the 2nd argument
    p2 = re.compile(
        r'(broadcast_to_desktop_clients\([^,]+,' + s + quote + r')' + escaped + r'(' + quote + r')'
    )
    r2 = r'\1' + EVENT_MAPPING[old_name] + r'\2'
    patterns.append((p2, r2))

    # Pattern 3: sio.emit / socket_server.emit at module level (less common)
    # Covers: await sio.emit("control", ...) in routes.py inline handlers
    # Same regex as Pattern 1 — .emit( catches these too.

    return patterns

# ──────────────────────────────────────────────────────────
# MIGRATION LOGIC
# ──────────────────────────────────────────────────────────

def find_files(base: Path, globs: list[str]) -> list[Path]:
    """Find all files matching the glob patterns."""
    files = []
    for g in globs:
        files.extend(base.glob(g))
    return sorted(set(files))

def migrate_file(filepath: Path, dry_run: bool) -> tuple[int, list[str]]:
    """
    Migrate a single file. Returns (num_changes, list_of_change_descriptions).
    """
    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        return (0, [f"ERROR reading {filepath}: {e}"])

    original = content
    changes = []

    for old_name in EVENT_MAPPING:
        for pattern, replacement in build_patterns(old_name):
            matches = pattern.findall(content)
            if matches:
                new_content = pattern.sub(replacement, content)
                if new_content != content:
                    count = len(matches)
                    changes.append(
                        f"  {old_name:>30s} → {EVENT_MAPPING[old_name]:<30s} ({count}x)"
                    )
                    content = new_content

    if content != original:
        if not dry_run:
            filepath.write_text(content, encoding="utf-8")
        return (len(changes), changes)
    else:
        return (0, [])

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
    # Determine project root (parent of scripts/)
    project_root = Path(__file__).resolve().parent.parent

    backend_base = project_root / BACKEND_DIR
    frontend_base = project_root / FRONTEND_DIR

    print("=" * 70)
    print("  Socket.IO Event Name Migration")
    print(f"  Mode: {'DRY-RUN (no files written)' if args.dry_run else 'EXECUTE'}")
    print("=" * 70)

    targets = [
        ("BACKEND", backend_base, BACKEND_GLOBS),
        ("FRONTEND", frontend_base, FRONTEND_GLOBS),
    ]

    total_files_changed = 0
    total_changes = 0

    for label, base, globs in targets:
        if not base.exists():
            print(f"\n[{label}] Skipped — directory not found: {base}")
            continue

        files = find_files(base, globs)
        print(f"\n[{label}] Scanning {len(files)} files in {base}")

        label_changes = 0
        label_files = 0

        for f in files:
            num, details = migrate_file(f, args.dry_run)
            if num > 0:
                label_files += 1
                label_changes += num
                rel = f.relative_to(project_root)
                print(f"\n  📄 {rel}")
                for d in details:
                    print(d)

        total_files_changed += label_files
        total_changes += label_changes
        print(f"\n[{label}] {label_files} files, {label_changes} event renames")

    print("\n" + "=" * 70)
    print(f"  TOTAL: {total_files_changed} files changed, {total_changes} event renames")
    if args.dry_run:
        print("  (dry-run — no files were modified)")
        print("  Re-run without --dry-run to apply changes.")
    else:
        print("  Migration complete. Please verify with grep and tests.")
    print("=" * 70)

    return 0


if __name__ == "__main__":
    sys.exit(main())
