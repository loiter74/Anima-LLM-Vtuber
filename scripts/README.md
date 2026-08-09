# Animetta Utility Scripts

Operational, quality-gate, and acceptance scripts for the Anima VTuber project.
All Python scripts target **Python 3.13** (`py -3.13`). Run from the repository
root with `PYTHONPATH=src`.

## Runtime lifecycle & release gates

| Script | Purpose |
|--------|---------|
| `runtime_lifecycle.py` | Cross-platform lifecycle for the host-local Qwen TTS service and the Animetta Docker compose project (`host-tts-up/status/stop`, `anima-up/down`) |
| `release_runtime_gate.py` | Production release gate for full/nightly CI: verifies host Qwen identity, cold-builds the image, requires app health + frontend HTTP + clean logs |
| `qwen_preflight.py` | Read-only readiness preflight for the persistent local Qwen TTS service on `:8767` |
| `soak_golden_path.py` | Real 600 s / 12-turn golden-path acceptance gate |
| `baseline_golden_path.py` | Captures fail-closed evidence for the golden-path baseline |
| `probe_release_turn.py` | Probes one production Socket.IO turn for typed TTS degradation |

## Health & quality gates

| Script | Purpose |
|--------|---------|
| `health_check.py` | Repository health gate runner with `quick/affected/full/docker` profiles |
| `check_source_standards.py` | Validates every tracked operational source file (Dockerfile/shell/yaml/json/toml) |
| `check_secrets.py` | Scans tracked config files for plaintext secrets |
| `check_minecraft_architecture.py` | Reports/enforces Minecraft control-plane boundaries |
| `route_smoke.py` | Lightweight ASGI route probes with mocked model prewarm |
| `validate-events.py` | Validates Socket.IO event-name consistency across config, Python, and TS (called during Docker build) |

## Minecraft acceptance & contract generation

Gameplay workflows are submitted through the durable single-consumer control
plane (`mc_connection` / `mc_operate_bot`), through mc-mcp rather than direct launch.

| Script | Purpose |
|--------|---------|
| `minecraft_adaptive_showcase.py` | Runs the complete real adaptive Minecraft showcase and packages evidence |
| `minecraft_adaptive_micro_gate.py` | Runs one lowest-layer real Minecraft gate without the full R8 scene |
| `minecraft_real_model_contract.py` | Captures a real-model natural-language → MissionSpec contract result |
| `voyager_real_e2e.py` | Real GameBot v2 acceptance: cooperative stop and disconnect quarantine |
| `verify_minecraft_migration.py` | Verifies additive control-plane migration on a backed-up skill DB |
| `generate_gamebot_v2_contracts.py` | Generates canonical GameBot v2 JSON schema and golden messages |
| `generate_minecraft_mission_contracts.py` | Generates the versioned adaptive Minecraft mission contract bundle |

## Review harnesses (loopback-only)

| Script | Purpose |
|--------|---------|
| `minecraft_gameplay_review_harness.py` | Loopback-only Minecraft gameplay review harness (uvicorn) |
| `tts_failover_review_harness.py` | Loopback-only OBS TTS failover review harness (uvicorn) |

## Benchmarks & smoke gates

| Script | Purpose |
|--------|---------|
| `bench.py` | LangGraph pipeline latency benchmark suite (`quick/full/compare/report`) |
| `benchmark_host_tts.py` | Measures the authenticated Windows host TTS streaming contract |
| `smoke_real_profile.py` | Real DeepSeek/MiMo smoke gate with sanitized evidence |
| `smoke_bilibili_room.py` | Opt-in real Bilibili room handshake smoke (never starts the AI pipeline) |

## Danmaku collection

Bilibili 进程级实时会话由开发智能体 MCP 控制：
`py -3.13 -m tooling.bilibili_mcp`。MCP 只连接已运行的 Animetta Socket.IO
服务，不创建第二条 Bilibili 网关连接。下列脚本只负责数据采集，不负责直播会话控制。

| Script | Purpose |
|--------|---------|
| `collect_danmaku.py` | Builds danmaku sample datasets from trending videos via `MemeCollector` |
| `collect_live_danmaku.py` | Collects normalized live-room danmaku to local CSV/JSONL |

## Utilities

| Script | Purpose |
|--------|---------|
| `reset_observability.py` | Deletes disposable observation DBs and bootstraps schema version 2 |
| `sync_feishu_to_docs.py` | Syncs project data from Feishu sheets to docs via `lark-cli` (cron) |
| `tts_audition.py` | Anonymous DashScope emotive TTS audition (24 samples, no Docker) |
| `download-models.sh` | Pre-downloads Kokoro / Qwen3 / Whisper models via `huggingface_hub` |

## Training pipeline (`train/`)

One-command RVC v2 singing-model training.

```
train/
├── cli.py              ← Main entry: python -m scripts.train.cli --character <name>
├── config.yaml          ← Training configuration
├── prepare_data.py      ← Stage 1: preprocess audio
└── deploy.py            ← Stage 3: deploy model to Anima config
```

```bash
# Full pipeline
python -m scripts.train.cli --character shige_utage

# Dry run (check config)
python -m scripts.train.cli --character shige_utage --dry-run

# Deploy only
python -m scripts.train.cli --character shige_utage --deploy-only
```
