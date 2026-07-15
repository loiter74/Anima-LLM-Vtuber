# Runtime Config Reload

Animetta atomically reloads the canonical runtime manifest for persona content and allowlisted lightweight settings without restarting the server.

## Scope

Reload currently covers:

- `config/animetta.yaml` `application.persona`
- the selected `config/personas/*.yaml` content
- selected LLM `temperature`, `top_p`, `max_tokens`, and DeepSeek `thinking`
- subtitle and active-meme UI toggles

Profile, provider reference, provider type, model, voice, endpoint, authentication, policy, and service lifecycle changes return `restart_required` and preserve the current snapshot and engines.

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
  "error": null,
  "effective_hash": "...",
  "semantic_hash": "...",
  "restart_required": []
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
