# Security Notes

## Credential Handling

- Store real provider credentials in `.env`, local environment variables, or a deployment secret manager.
- Keep tracked config files on placeholders such as `${MIMO_API_KEY}` or `your_api_key_here`.
- Run `python scripts/check_secrets.py` before sharing changes that touch `config/*.yaml` or `.env.example`.
- Do not paste API keys, tokens, passwords, or signed URLs into issues, logs, screenshots, or planning artifacts.

## Credential Rotation

If a credential is committed, pushed, or shared:

1. Revoke or rotate it at the provider immediately.
2. Replace the tracked value with an environment variable placeholder.
3. Audit CI logs, release artifacts, and deployment config for copies of the value.
4. Record the provider, affected scope, rotation time, and follow-up owner in the incident notes.
5. Treat history rewriting as a separate repository-maintenance task; rotation is required even if history is cleaned.
