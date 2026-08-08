# Zeabur Deployment

Animetta's hosted descriptor builds the lightweight core image from `Dockerfile` and runs the canonical `production` profile. Qwen inference is never bundled into that image; it must be supplied by a separately reachable host service when the production failover selects it.

## Required inputs

Configure these in Zeabur's secret/environment settings:

| Variable | Purpose |
|---|---|
| `ANIMETTA_PROFILE=production` | Select the complete production map in `config/animetta.yaml` |
| `ANIMETTA_HOST=0.0.0.0` | Bind the core service |
| `ANIMETTA_PORT=12394` | Internal backend port |
| `DEEPSEEK_API_KEY` | Remote LLM authentication |
| `MIMO_API_KEY` | Remote ASR/VAD authentication |
| `DASHSCOPE_API_KEY` | Beijing DashScope realtime TTS authentication for production Seren |

Set `QWEN_HOST_TTS_URL` to a Qwen endpoint reachable from Zeabur and provide `QWEN_TTS_API_KEY` when the production failover includes Qwen. The desktop default `127.0.0.1:8767` and Docker Desktop name `host.docker.internal` are not valid hosted endpoints.

Provider names, models, and voices are not environment settings. Change them only in `config/animetta.yaml`, then redeploy.

## Deploy and verify

1. Import the repository and select the repository `zeabur.json` descriptor.
2. Add the required secrets above.
3. Deploy the backend service.
4. Verify `GET /health` returns HTTP 200.
5. Verify `GET /ready` reports `production`, matching configured/resolved identities, and no `reason` values.

The browser uses same-origin Socket.IO and relative API paths. No frontend backend-URL build variable is required; nginx routes `/socket.io`, `/api`, `/health`, and `/ready` to the core service.
