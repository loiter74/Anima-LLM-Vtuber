# Docker Deployment Guide

Animetta ships as a single Docker container with nginx (static frontend + reverse proxy) and the Python backend.

## Prerequisites

- **Docker** 24.0+ with Docker Compose v2
- **NVIDIA Container Toolkit** (for GPU inference)

### Install NVIDIA Container Toolkit

```bash
# Ubuntu/Debian
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Verify: `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`

## Quick Start

```bash
# 1. Clone and configure
git clone https://github.com/loiter74/animetta.git && cd animetta
cp .env.example .env
# Edit .env with your API keys. Do not commit real credentials.

# 2. Build and start (GPU)
docker compose up -d --build

# 3. Open http://localhost
```

The container exposes:
- **Port 80** — nginx (frontend + API proxy)
- **Port 12394** — backend direct access (optional)

## GPU vs CPU Deployment

| | GPU (`docker-compose.yml`) | CPU (`docker-compose.cpu.yml`) |
|---|---|---|
| TTS | Kokoro (GPU-accelerated) | Kokoro (CPU fallback) |
| ASR | Whisper (faster-whisper, GPU) | Whisper (CPU) |
| Command | `docker compose up -d` | `docker compose -f docker-compose.cpu.yml up -d` |

```bash
# GPU (default)
docker compose up -d --build

# CPU-only
docker compose -f docker-compose.cpu.yml up -d --build
```

## Volume Mounts

| Volume | Container Path | Purpose |
|---|---|---|
| `animetta-memory-db` | `/app/memory_db` | Wiki memory, Chroma vector DB, SQLite |
| `animetta-data` | `/app/data` | Downloaded models, stats |
| `.env` (bind) | `/app/.env` | API keys (read-only) |

Named volumes persist across container rebuilds. To reset data:

```bash
docker compose down -v   # WARNING: deletes all memory and model data
```

## Environment Variables

Set in `.env` or pass via `docker compose`:

| Variable | Default | Description |
|---|---|---|
| `MIMO_API_KEY` | — | Mimo provider API key |
| `GLM_API_KEY` | — | Zhipu AI API key |
| `OPENAI_API_KEY` | — | OpenAI/DeepSeek API key |
| `OPENAI_BASE_URL` | — | Custom OpenAI-compatible endpoint |
| `ANIMETTA_LOG_LEVEL` | `INFO` | Logging level (DEBUG/INFO/WARNING/ERROR) |

Service overrides (in `.env`):

| Variable | Options | Default |
|---|---|---|
| `ANIMETTA_LLM` | `deepseek`, `glm`, `openai`, `ollama` | `deepseek` |
| `ANIMETTA_TTS` | `vibe_voice`, `kokoro`, `openai`, `mock` | `vibe_voice` |
| `ANIMETTA_ASR` | `faster_whisper`, `openai`, `funasr`, `mock` | `faster_whisper` |

## Troubleshooting

### Container won't start

```bash
docker compose logs -f animetta   # Check startup logs
```

### GPU not detected

```bash
# Verify NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi

# Check inside container
docker compose exec animetta python -c "import torch; print(torch.cuda.is_available())"
```

### Health check failing

```bash
# Wait 2 minutes (model loading), then:
curl http://localhost/health
# Expected: {"status": "ok", ...}
```

### Models not downloading

Check if the download script ran in logs. Manually trigger:

```bash
docker compose exec animetta bash scripts/download-models.sh
```

### Frontend not loading

```bash
# Rebuild frontend
docker compose build --no-cache animetta
docker compose up -d
```

### Permission errors on volumes

```bash
# Fix ownership
docker compose exec animetta chown -R root:root /app/memory_db /app/data
```

## Building Locally

```bash
# Full rebuild (no cache)
docker compose build --no-cache

# Rebuild only frontend
docker build --target frontend-builder -t animetta-frontend .

# Check image size
docker images animetta
```
