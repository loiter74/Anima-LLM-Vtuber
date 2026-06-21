# Minecraft Manual Integration Scripts

Manual smoke/integration scripts for the Minecraft bot subsystem. **Not pytest tests** — these connect to a real Minecraft server and require manual execution.

## Scripts

| Script | Purpose |
|--------|---------|
| `smoke_bot.py` | Basic bridge connection smoke test |
| `smoke_skill_system.py` | Skill library + predefined skills loading |
| `smoke_skill_extraction.py` | Full extraction flow: connect → execute task → trace → extract skill |
| `smoke_real_skill_extraction.py` | Same as above but with real MC server interaction |
| `smoke_tech_tree.py` | TechTreeRunner simulation with mock bridge (no real server needed) |
| `debug_tech_tree.py` | TechTreeRunner with verbose debug logging |
| `run_tech_tree.py` | Full autonomous tech tree unlock run (~1 hour target) |

## Usage

All scripts require `animetta` on `sys.path` (handled internally via `../../src`).

```bash
# From project root
python scripts/minecraft_manual/smoke_bot.py

# Debug mode
python scripts/minecraft_manual/debug_tech_tree.py
```

Requires a running Minecraft server on `localhost:25565` (except `smoke_tech_tree.py` which uses mocks).
