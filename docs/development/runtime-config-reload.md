# Runtime Config Reload

Animetta supports runtime reload for persona YAML and lightweight LLM settings without restarting the server.

## Scope

Reload currently covers:

- `config/personas/*.yaml`
- `config/config.yaml` persona selection
- `config/services.yaml` lightweight LLM fields: `model`, `temperature`, `top_p`, `max_tokens`, and DeepSeek `thinking`

Reload does not recreate heavyweight services such as ASR, TTS, VAD, model managers, or network clients. Change those by restarting the service.

## API

Trigger a reload:

```bash
curl -X POST http://localhost/api/config/reload
```

Success response:

```json
{
  "ok": true,
  "version": 2,
  "persona": "anima.v0.1",
  "refreshed": ["persona", "llm"],
  "error": null
}
```

Failure response keeps the previous valid runtime config active:

```json
{
  "ok": false,
  "version": 1,
  "persona": "anima.v0.1",
  "refreshed": [],
  "error": "validation error"
}
```

Errors redact likely API keys before returning to the frontend or logs.

## Frontend

The side panel reload button calls `POST /api/config/reload` and shows loading, success, or failure state. It does not insert system messages into the chat timeline, so the active conversation layout and scroll position remain stable.

## Docker

Both Docker Compose files mount `./config` into `/app/config:ro`. Edit config files on the host, then trigger reload from the UI or API. The read-only mount is intentional: runtime reload reads config changes but never writes generated config back into the repository.

## Verification

After changing persona or LLM settings:

1. Trigger reload from the side panel or `curl`.
2. Confirm the response has `"ok": true` and an incremented `version`.
3. Send the next user message; new prompt construction includes the updated persona and `config_version`.
4. If the reload fails, fix the YAML or validation error and retry. The previous valid persona and LLM settings remain active until a successful reload.
