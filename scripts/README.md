# Animetta Utility Scripts

Development and training utilities for the Anima VTuber project.

## Scripts

| Script | Purpose |
|--------|---------|
| `anima_cli.py` | RVC training CLI wrapper |
| `bench.py` | LangGraph pipeline performance benchmark |
| `check_secrets.py` | Tracked config secret scanner |
| `health_check.py` | Local health gate orchestrator |
| `route_smoke.py` | Lightweight ASGI route probes |
| `validate-events.py` | Socket.IO event contract validator |
| `download-models.sh` | Pre-download AI models (Kokoro, Qwen3, Whisper) |
| `collect_danmaku.py` | Build danmaku sample datasets |
| `analyze_danmaku_opencode.py` | Analyze collected danmaku samples |
| `e2e_test_events.py` | Socket event end-to-end checks |
| `start-mc-bot.bat` | Windows helper for the Minecraft bot |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `minecraft_manual/` | Manual Minecraft skill, tech-tree, and bot smoke scripts |
| `train/` | Character singing model training pipeline |

## Training Pipeline

```
train/
├── cli.py              ← Main entry: python -m scripts.train.cli --character <name>
├── config.yaml          ← Training configuration
├── prepare_data.py      ← Stage 1: preprocess audio
└── deploy.py            ← Stage 3: deploy model to Anima config
```

Usage:
```bash
# Full training pipeline
python -m scripts.train.cli --character shige_utage

# Dry run (check config)
python -m scripts.train.cli --character shige_utage --dry-run

# Deploy only
python -m scripts.train.cli --character shige_utage --deploy-only
```
