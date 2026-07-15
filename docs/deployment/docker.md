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

Verify: `docker run --rm --gpus all nvidia/cuda:12.8.2-base-ubuntu24.04 nvidia-smi`

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
| Profile | `production` | `smoke` |
| LLM | DeepSeek remote API | DeepSeek remote API |
| TTS | Isolated Qwen3 Alice GPU service | MiMo remote API |
| ASR / VAD | MiMo remote API | MiMo remote API |
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
| `.env` (Compose interpolation) | not mounted | Supplies only explicitly listed profile secrets/endpoints |

Named volumes persist across container rebuilds. To reset data:

```bash
docker compose down -v   # WARNING: deletes all memory and model data
```

## Environment Variables

Set in `.env` or pass via `docker compose`:

| Variable | Default | Description |
|---|---|---|
| `MIMO_API_KEY` | — | Mimo provider API key |
| `DEEPSEEK_API_KEY` | — | DeepSeek LLM API key |
| `QWEN_TTS_API_KEY` | — | Shared authentication for the isolated Qwen TTS service |
| `QWEN_TTS_URL` | profile/Compose value | Qwen TTS service endpoint |
| `ANIMETTA_PROFILE` | required | `test`, `smoke`, or `production` |
| `ANIMETTA_HOST` / `ANIMETTA_PORT` | required | Core bind endpoint |

Provider names, models, and voices are selected only in `config/animetta.yaml`; deployment environment variables cannot override them.

## Troubleshooting

### Container won't start

```bash
docker compose logs -f animetta   # Check startup logs
```

### GPU not detected

```bash
# Verify NVIDIA runtime
docker run --rm --gpus all nvidia/cuda:12.8.2-base-ubuntu24.04 nvidia-smi

# Check inside container
docker compose exec qwen-tts python -c "import torch; print(torch.cuda.is_available())"
```

### Health check failing

```bash
# Wait 2 minutes (model loading), then:
curl http://localhost/health
# Expected: {"status": "ok", ...}
```

### Qwen model or Alice prompt is unavailable

The production worker is intentionally offline and never downloads weights during
readiness. Set `HF_CACHE_DIR` to a populated Hugging Face cache and
`ALICE_REF_AUDIO` to the Alice reference WAV, then recreate `qwen-tts`.

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
