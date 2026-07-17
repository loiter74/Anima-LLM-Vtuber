# Deployment Guide

## Prerequisites

- [flyctl](https://fly.io/docs/flyctl/install/) CLI installed
- Fly.io account (free tier: 3 VMs, 3GB storage)
- API keys for the services you want to use

## One-Click Deploy

```bash
# 1. Login
flyctl auth login

# 2. Set secrets (API keys)
flyctl secrets set DEEPSEEK_API_KEY=your_key_here
flyctl secrets set MIMO_API_KEY=your_key_here
flyctl secrets set DASHSCOPE_API_KEY=your_beijing_model_studio_key
# Optional manual local-Qwen rollback only:
# flyctl secrets set QWEN_TTS_API_KEY=your_internal_auth_token

# 3. Launch
flyctl launch --ha=false

# 4. Verify
curl https://animetta-demo.fly.dev/health
```

Expected response:
```json
{"status": "ok", "service": "animetta", "timestamp": 1714512345.678}
```

## Free Tier Config

The `fly.toml` is configured for Fly's free tier:
- **Scale to zero**: VMs stop when idle, start on first request
- **512MB RAM**: Sufficient for mock/API-only mode
- **Hong Kong region**: Low latency for Asia

## Local Test Profile (No API Keys)

For a local validation without API keys, use the manifest's fixed test profile:

```bash
ANIMETTA_PROFILE=test docker compose -f docker-compose.core.yml up -d --build
```

The app will respond with canned responses. Socket.IO and Live2D still work.

## Production Mode

```bash
# More resources
flyctl scale vm shared-cpu-2x --group web
flyctl scale memory 1024

# Custom domain
flyctl certs add your-domain.com
```

## Health Check

Endpoint: `GET /health`

```json
{
  "status": "ok",
  "service": "animetta",
  "timestamp": 1714512345.678
}
```

The Dockerfile includes a Docker HEALTHCHECK that pings this endpoint every 30s.
