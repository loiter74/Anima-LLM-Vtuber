# Remove Minecraft Web UI Plan

Date: 2026-07-04

## Goal

Remove the Minecraft bot browser web UI/debug viewer stack.

This targets the Mineflayer/prismarine browser viewer and HUD served around port `3007`. It does not remove the Animetta main web frontend, the native Minecraft client, SpectatorPlus, or the client-side Fabric mod workflow.

## Keep

- Native Minecraft client usage for visual inspection and spectating.
- SpectatorPlus server/client setup.
- `C:/Users/30262/Project/voyager-mc-bot/src/clientViewer.js`.
- `MinecraftClientViewerConfig` and `client_viewer` config.
- Spectator control APIs and bot connection logic.
- Minecraft server Docker setup.

## Remove Scope

1. Remove browser viewer entry points:
   - `C:/Users/30262/Project/voyager-mc-bot/src/viewer.js`
   - `C:/Users/30262/Project/voyager-mc-bot/src/viewer.test.js`

2. Remove web viewer wiring from the Node bot:
   - Delete `webViewerConfigFromEnv` import/use in `C:/Users/30262/Project/voyager-mc-bot/src/index.js`.
   - Delete `maybeStartFirstPersonViewer` import/use in `C:/Users/30262/Project/voyager-mc-bot/src/index.js`.
   - Ensure bot startup still works with `node src/index.js <host> <port> <username> <version>`.

3. Remove Python config and environment export:
   - Delete `MinecraftWebViewerConfig` from `src/animetta/tools/minecraft/core/config.py`.
   - Delete the `web_viewer` field from `MinecraftConfig`.
   - Delete `MC_WEB_VIEWER_*` environment variables from `src/animetta/tools/minecraft/core/bridge.py`.

4. Remove unused Node dependencies after confirming no other files use them:
   - `prismarine-viewer`
   - `minecraft-assets`
   - `express`, only if it is not used elsewhere in the Minecraft bot package.

5. Update tests:
   - Remove `web_viewer` assertions from `tests/tools/minecraft/core/test_config.py`.
   - Remove or adjust any tests expecting `MC_WEB_VIEWER_*` environment variables.
   - Keep client viewer and spectator tests intact.

6. Update documentation:
   - Remove browser debug viewer sections from `docs/minecraft/client-viewer.md`.
   - Update any architecture or setup docs that mention `web_viewer`, prismarine viewer, or port `3007`.
   - Keep native client viewer and SpectatorPlus instructions.

## Verification

Run these checks after deletion:

```powershell
rg -n "web_viewer|MC_WEB_VIEWER|prismarine-viewer|minecraft-assets|maybeStartFirstPersonViewer|webViewerConfigFromEnv|3007" src tests docs config
Push-Location C:/Users/30262/Project/voyager-mc-bot
node --check src/index.js
npm test
Pop-Location
python -m pytest -o addopts='' tests/tools/minecraft/core/test_config.py tests/tools/minecraft/core/test_bridge.py tests/tools/minecraft/core/test_client_viewer_bridge.py tests/tools/minecraft/test_spectator.py -q
ruff check src/animetta/tools/minecraft/core tests/tools/minecraft
```

Then run the Minecraft smoke check:

1. Start or confirm `animetta-mc` is healthy.
2. Start the host Node bot with Minecraft version `1.21`.
3. Confirm `AnimettaBot` joins the server.
4. Confirm `/spectate AnimettaBot <player>` still works from RCON or in-game command flow.

## Rollback

If removal breaks bot startup or spectator behavior:

1. Restore `viewer.js` and `viewer.test.js`.
2. Restore `MinecraftWebViewerConfig` and `MC_WEB_VIEWER_*` exports.
3. Restore the removed package dependencies.
4. Re-run the verification commands above.
