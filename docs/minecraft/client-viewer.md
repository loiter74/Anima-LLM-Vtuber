# Minecraft viewer attachment

Viewer attachment is owned entirely by `mc-mcp` and its Mineflayer-side viewer
controller. Anima only displays the projected state and exposes a manual retry via
`mc_connection(operation="reattach_viewer")`.

Configure the selected profile in this repository's
`services/mc-mcp/config/mc-mcp.json`:

```json
{
  "viewer": {
    "username": "CameraGuy",
    "auto_attach": true,
    "required": false,
    "attach_timeout_ms": 30000
  }
}
```

The controller retries with bounded backoff when the viewer joins, the bot starts or
respawns, the bot changes dimension, the runtime restarts, or the periodic check finds
the binding absent. `required=true` prevents the connection from becoming `ready`
until attachment is confirmed. Optional attachment failure leaves the bot usable and
appears as a warning state.

The UI shows three independent layers: server, bot and viewer. If viewer attachment
fails, verify the selected mc-mcp profile's server permissions and use “重新附身” to
ask the service-side controller to retry. Do not add retry, username or operator
policy to Anima configuration.
