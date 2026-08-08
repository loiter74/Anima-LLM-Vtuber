# Docker Deployment Guide

Animetta uses one Compose project for the application container. Qwen3-TTS is a
Windows-host service on `127.0.0.1:8767`; it is not built, started, or stopped by
Docker.

## Prerequisites

- Docker 24.0+ with Docker Compose v2
- Python 3.13 available through `py -3.13`
- The configured host Qwen runtime and model files
- API keys required by the selected Animetta profile

Copy `.env.example` to `.env`, then set at least the selected provider keys and
`QWEN_TTS_API_KEY`.

## Start

```powershell
# Start or reuse the host-local Qwen process and verify exact readiness.
py -3.13 scripts/runtime_lifecycle.py host-tts-up

# Build and start only the Animetta application container.
py -3.13 scripts/runtime_lifecycle.py anima-up
```

The application container reaches Qwen at `http://host.docker.internal:8767`.
The lifecycle fails closed if host Qwen health, authentication, or model identity
does not match before the Animetta build starts.

Once ready:

- Frontend: `http://localhost`
- Backend health: `http://localhost/health`
- Backend direct port: `http://localhost:12394`

CPU/smoke mode does not select local Qwen:

```powershell
docker compose -f docker-compose.cpu.yml up -d --build
```

## Lifecycle

```powershell
# Stop only Animetta; preserve the loaded host Qwen model.
py -3.13 scripts/runtime_lifecycle.py anima-down

# Inspect the host service.
py -3.13 scripts/runtime_lifecycle.py host-tts-status

# Explicitly release host Qwen GPU memory.
py -3.13 scripts/runtime_lifecycle.py host-tts-stop

# Application logs.
docker compose logs -f animetta
```

There is no Qwen Dockerfile, Qwen Compose project, or Qwen container lifecycle
command. Changing host Qwen code or models requires restarting the host service,
not rebuilding the application image.

## Configuration

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Production LLM credential |
| `DASHSCOPE_API_KEY` | Production primary TTS credential |
| `MIMO_API_KEY` | Smoke or fallback provider credential |
| `QWEN_TTS_API_KEY` | Bearer token shared with the host Qwen service |
| `QWEN_HOST_TTS_URL` | Host endpoint; local default is `http://127.0.0.1:8767` |

Provider selection remains in `config/animetta.yaml`. Compose supplies the
container-visible Qwen endpoint as `http://host.docker.internal:8767`.

## Troubleshooting

If `host-tts-up` fails, run `host-tts-status` and inspect the log path printed by
the command. Verify that port 8767 is free, the bearer token matches, and the
reported runtime/model/voice identity is exact.

If Animetta fails after Qwen is ready:

```powershell
docker compose ps
docker compose logs --no-color animetta
curl.exe -sS http://localhost/health
```

Normal application rebuilds must not stop or restart the host Qwen process.
