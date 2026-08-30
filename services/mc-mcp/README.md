# mc-mcp

Independent Mineflayer runtime and loopback Streamable HTTP MCP service.

The in-repository service was imported from the former mc-bot baseline commit
`94923f0eaf07bcf456bb277d4a00d97d7956c83c`. This directory is now the canonical
source and does not depend on another checkout.

## 运行方式

`mc-mcp` owns Minecraft server, bot, viewer controller and GameBot v2 runtime
lifecycle. Profiles live in `config/mc-mcp.json`:

- `managed`: starts and probes the repository-owned Compose service, then logs in the
  bot. Shutdown uses the exact persisted ownership identity.
- `external`: probes and connects to an existing server and never stops it.

```bash
npm ci --prefix services/mc-mcp
node services/mc-mcp/src/mcp/cli.js service ensure
node services/mc-mcp/src/mcp/cli.js connect
node services/mc-mcp/src/mcp/cli.js status
node services/mc-mcp/src/mcp/cli.js reattach-viewer
node services/mc-mcp/src/mcp/cli.js disconnect
node services/mc-mcp/src/mcp/cli.js shutdown
node services/mc-mcp/src/mcp/cli.js service stop
```

Run these commands from the repository root. Animetta automatically falls back to this
in-repository CLI entrypoint, so no global installation is required.

The default `connect` target is `external-local`, which reuses the existing server on
`127.0.0.1:25565`. Managed profiles cannot create a Compose project unless the caller
passes `--allow-create`; `prepare` also requires an explicit profile. This flag is for a
single user-approved isolated review or survival run, and that run must call `shutdown`
when it finishes.

`disconnect` stops only the bot. `shutdown` additionally stops only managed resources
owned by the current mc-mcp service. The HTTP endpoint defaults to
`http://127.0.0.1:8768/mcp` and requires a locally generated bearer token; CLI output
redacts it except for the machine-readable `service ensure` descriptor consumed by a
local client.

`prepare` is the deployment/bootstrap phase: it downloads and starts the managed server
without logging in the bot. Goal-serving deployments run it before accepting Minecraft
instructions. Connection profiles then enforce a 60-second command-to-`ready` SLO and reserve
45 seconds for server health and 10 seconds for bot login. The managed data volume is
retained across `shutdown`, so the server jar and world are reused instead of downloaded
and generated again. `MC_MCP_REQUEST_TIMEOUT_MS` may be lowered for stricter callers;
raising it does not relax the profile lifecycle deadline.

Use `managed-survival` for autonomous technology progression. It owns an isolated,
persistent default world on port `25567`; peaceful difficulty removes combat starvation
noise while preserving survival mining, crafting, smelting, tool tiers and natural ore
generation. The review profiles remain unchanged.

`mc-mcp service stop` stops the bot and local MCP HTTP service but preserves a managed
server and its ownership record. Use `mc-mcp shutdown` only when the owned server should
also be stopped.

## Viewer policy

Each profile can define `viewer.username`, `viewer.auto_attach` and
`viewer.required`. The Mineflayer viewer controller retries attachment after viewer
join, bot spawn/respawn, dimension changes and periodic checks. Required attachment
failure prevents `ready`; optional failure is reported without blocking the bot.

## Runtime contract

mc-mcp exposes lifecycle tools plus GameBot v2 manifest, observe, execute, inspect,
cancel, health and cursor-based event reads. The internal JSON-line process protocol
between mc-mcp and `src/index.js` is private to this repository. The bot child accepts
only GameBot v2 commands plus the bounded survival-review and viewer lifecycle commands;
the former v1 evaluator, arbitrary-code, Voyager mode and plan protocols are not exposed.

`src/runtime/gamebotV2Adapter.js` owns v2 capability and observation composition,
`src/runtime/processProtocol.js` owns the child-process envelope, and `src/mcp/` owns
profile, managed-server and HTTP MCP lifecycle concerns. The root
`contracts/gamebot/v2/` directory is the only contract source.

## Development

From the repository root:

```bash
npm test --prefix services/mc-mcp
npm run test:contract --prefix services/mc-mcp
npm run check --prefix services/mc-mcp
```
