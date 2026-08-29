# Docker Deployment Guide

Animetta uses one Compose project for the application container. Qwen3-TTS and
RVC are Windows-host services on `127.0.0.1:8767` and `127.0.0.1:8769`; they are
not built, started, or stopped by Docker.

## Prerequisites

- Docker 24.0+ with Docker Compose v2
- Python 3.13 available through `py -3.13`
- The configured host Qwen and RVC runtimes and model files
- API keys required by the selected Animetta profile

Copy `.env.example` to `.env`, then set at least the selected provider keys and
`QWEN_TTS_API_KEY`.

## Choose a startup path

### Build the current source

```powershell
# Start or reuse the host runtimes, verify them, build animetta:local, and start it.
py -3.13 scripts/runtime_lifecycle.py anima-up
```

Use `anima-up` while developing or when the running service must include the
current checkout. It always builds the local application image before starting
it. The lifecycle fails closed if either host runtime fails its readiness and
identity preflight.

### Deploy a CI-verified image

Every successful `main` quality gate publishes an application image to
`ghcr.io/loiter74/animetta`. Deploy it without a local application build:

```powershell
py -3.13 scripts/runtime_lifecycle.py anima-deploy --image ghcr.io/loiter74/animetta:sha-<40-character-commit>
```

The command starts or reuses both host runtimes, runs their preflights, pulls the
selected image and its Compose dependencies, starts Animetta with `--no-build`,
and verifies health, readiness, the frontend, and application logs. It records
the resolved image digest in the lifecycle evidence.

Accepted image references are:

- `ghcr.io/loiter74/animetta:main` for the latest successful `main` build;
- `ghcr.io/loiter74/animetta:sha-<40-lowercase-hex-commit>` for a reproducible
  commit build;
- `ghcr.io/loiter74/animetta@sha256:<64-lowercase-hex-digest>` for an immutable
  content-addressed deployment.

Prefer a full SHA tag or digest for rollback and repeatable environments. The
moving `main` tag is convenient for trying the latest build, but it does not pin
the deployed content.

Public packages can be pulled anonymously. For a private GHCR package, create a
GitHub token with `read:packages`, then authenticate Docker before deployment:

```powershell
$env:ANIMETTA_GHCR_TOKEN = "<token-with-read-packages>"
$env:ANIMETTA_GHCR_TOKEN | docker login ghcr.io -u loiter74 --password-stdin
Remove-Item Env:ANIMETTA_GHCR_TOKEN
```

`runtime_lifecycle.py` does not accept or store the token. Docker owns the login
credential. A denied pull fails closed and prompts you to run
`docker login ghcr.io`.

The application container reaches Qwen at `http://host.docker.internal:8767`
and RVC at `http://host.docker.internal:8769`. Both startup paths reuse the same
`docker-compose.yml`; CI and acceptance runs can select another
`ANIMETTA_PROFILE` without creating a second Compose topology.

Once ready:

- Frontend: `http://localhost`
- Backend health: `http://localhost/health`
- Backend direct port: `http://localhost:12394`

## Lifecycle

```powershell
# Stop only Animetta; preserve the loaded host Qwen and RVC models.
py -3.13 scripts/runtime_lifecycle.py anima-down

# Inspect the host services.
py -3.13 scripts/runtime_lifecycle.py host-tts-status
py -3.13 scripts/runtime_lifecycle.py host-rvc-status

# Explicitly release host-runtime GPU memory.
py -3.13 scripts/runtime_lifecycle.py host-tts-stop
py -3.13 scripts/runtime_lifecycle.py host-rvc-stop

# Application logs.
docker compose logs -f animetta
```

There is no Qwen or RVC Dockerfile, Compose service, or container lifecycle
command. Changing either host runtime or its models requires restarting that
host service, not rebuilding the application image.

## CI and branch protection

`.github/workflows/quality.yml` freezes an affected plan from
`tooling/quality.yml`, executes its Python, Node, service, and Docker groups, and
aggregates their results. On `main`, the same workflow publishes the SHA and
moving `main` image tags only after aggregation succeeds.

In the GitHub repository settings, protect `main` and require the status check
named **`quality-gate`** before merging. This remote setting is intentionally not
changed by repository scripts. Test selection and Docker scope mappings remain
authoritative only in `tooling/quality.yml`; do not duplicate them in the
workflow or branch-protection configuration.

## Configuration

| Variable | Purpose |
|---|---|
| `DEEPSEEK_API_KEY` | Production LLM credential |
| `DASHSCOPE_API_KEY` | Production primary TTS credential |
| `MIMO_API_KEY` | Smoke or fallback provider credential |
| `QWEN_TTS_API_KEY` | Bearer token shared with the host Qwen service |
| `QWEN_HOST_TTS_URL` | Host endpoint; local default is `http://127.0.0.1:8767` |
| `ANIMETTA_IMAGE` | Compose image override; lifecycle commands set this automatically |

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
Likewise, application rebuilds and image deployments must not stop or restart
host RVC. If a GHCR pull is denied, authenticate with `docker login ghcr.io` and
retry the exact same immutable image reference.
