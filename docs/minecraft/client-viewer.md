# Real Minecraft Client Viewer (Client Capture Mode)

This feature allows Animetta to use a **real Minecraft client** as the visual presentation layer while the Mineflayer bot handles AI decision-making and actions. This produces a native first-person view suitable for streaming (Neuro-sama style).

## How It Works

```
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   Mineflayer Bot │    │  Real MC Client   │    │  OBS / Capture   │
│   (AI actions)   │    │  (viewer account) │    │  (broadcast)     │
│                  │    │                   │    │                  │
│  moves, mines,   │    │  spectates bot,   │    │  captures client │
│  crafts, fights  │    │  provides native  │    │  window for      │
│                  │    │  first-person view│    │  streaming       │
└────────┬─────────┘    └────────┬──────────┘    └──────────────────┘
         │                       │
         └─────── Same MC server ┘
```

- **Mineflayer bot** (`AnimaBot`): The AI-controlled player that performs all actions.
- **Viewer account** (e.g., `CameraGuy`): A real Minecraft client that spectates the bot, providing the native first-person view.
- The bot auto-detects when the viewer account is online and attempts `/spectate` binding.

## Prerequisites

1. **Minecraft Java Edition** — a second account for the viewer client.
2. **A Minecraft server** with operator permissions (for `/spectate` and `/gamemode spectator` commands).
3. **OBS Studio** or similar screen capture software (for streaming/recording).

## Setup

### 1. Configure the viewer account

Add to your `config/services.yaml` or environment:

```yaml
minecraft:
  enabled: true
  client_viewer:
    enabled: true
    username: "CameraGuy"    # Your viewer MC account username
    mode: "spectator"        # Only "spectator" is supported in phase 1
    auto_spectate: true      # Auto-bind when viewer comes online
    poll_interval: 30        # Seconds between viewer-online checks
    spectate_timeout: 10     # Seconds to wait for spectate command
```

Or via environment variables:

```bash
MC_CLIENT_VIEWER_ENABLED=true
MC_CLIENT_VIEWER_USERNAME=CameraGuy
MC_CLIENT_VIEWER_MODE=spectator
MC_CLIENT_VIEWER_AUTO_SPECTATE=true
MC_CLIENT_VIEWER_POLL_INTERVAL=30
MC_CLIENT_VIEWER_SPECTATE_TIMEOUT=10
```

### 2. Start the Minecraft server

The server must be running and accessible. The bot connects to the server configured in `minecraft.bot.host:port`.

### 3. Start Animetta (bot)

Start Animetta as usual. The bot will connect and wait for the viewer account.

### 4. Start the real Minecraft client

1. Launch Minecraft Java Edition.
2. Log in with the **viewer account** (e.g., `CameraGuy`).
3. Connect to the **same server** as the bot.
4. The bot will auto-detect the viewer and attempt to spectate.

### 5. Verify spectate binding

The bot outputs status events:

| State | Meaning |
|-------|---------|
| `waiting` | Viewer account not yet online — start the client |
| `online` | Viewer detected on server — auto-spectate will trigger |
| `online` + `spectate_command_sent` | Spectate commands were sent, but the server has not confirmed binding yet |
| `following` | Server confirmed the viewer is spectating the bot — native view active |
| `failed` | Spectate command failed (permissions?) — see fallback |

Check logs for: `[clientViewer] viewer "CameraGuy" is online`, `[clientViewer] spectate command sent (state=online, unconfirmed)`, and then `[clientViewer] spectate confirmed (state=following)`.

## OBS / Window Capture Workflow

### Recommended setup

1. **Open OBS Studio**.
2. Add a **Window Capture** or **Game Capture** source.
3. Select the Minecraft client window.
4. Crop to remove the Minecraft title bar and any OS chrome.
5. Optionally add overlays (webcam, chat, alerts) around the Minecraft view.

### Scene suggestions

| Scene | Content |
|-------|---------|
| Gameplay | Full Minecraft client capture + overlays |
| Chat | Minecraft view + chat panel overlay |
| Starting Soon | Waiting screen while viewer account connects |
| BRB | Pause screen when bot is idle |

### Tips

- The viewer client should be in **fullscreen** or **maximized** for clean capture.
- Disable the viewer client's HUD elements you don't want (e.g., F1 to hide HUD if you use a custom overlay).
- Keep the Minecraft client's render distance reasonable for performance.

## Fallback Behavior

### When spectator permissions are unavailable

If the server does not grant operator permissions or the `/spectate` command is not available:

1. The bot emits a `client_viewer_status` event with `state: "failed"` and an error message if the server rejects the command.
2. The Mineflayer action bot **continues running normally** — all AI actions are unaffected.
3. You can manually spectate the bot using server commands or a camera mod.
4. The **browser debug viewer** (`prismarine-viewer`) remains available as a fallback visual:
   ```yaml
   minecraft:
     web_viewer:
       enabled: true
       port: 3007
   ```
   Note: The browser viewer is debug-only and does not provide native Minecraft rendering.

### When the viewer account goes offline

1. The bot transitions to `waiting` state.
2. When the viewer reconnects, the bot re-detects and sends spectate commands automatically.
3. Periodic polling (every 30 seconds by default) ensures reconnection is detected.

### When the spectate binding breaks

Spectate can break due to:
- Bot death and respawn
- Bot changing dimensions (Nether/End)
- Server teleportation

The bot automatically sends spectate commands on `spawn` events and periodically checks for the viewer account. The status only changes to `following` after a server confirmation message is observed.

## Configuration Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `false` | Enable real-client capture mode |
| `username` | string | `""` | MC username of the viewer account |
| `mode` | string | `"spectator"` | Binding mode (only `"spectator"` in phase 1) |
| `auto_spectate` | bool | `true` | Auto-run `/spectate` when viewer is online |
| `poll_interval` | int | `30` | Seconds between viewer-online polling checks |
| `spectate_timeout` | int | `10` | Seconds to wait for spectate command result |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| State stays `waiting` | Start the viewer client and connect to the server |
| State is `failed` | Check server operator permissions for the bot account |
| State remains `online` after command sent | Check server chat/log output; no confirmation message was observed |
| Viewer sees third-person | Ensure `/spectate <botName> <viewerName>` syntax is correct and accepted by the server |
| View jitters or disconnects | The bot sends spectate commands automatically; wait for `following` confirmation |
| Browser viewer shows but no native view | `client_viewer.enabled` must be `true` |
