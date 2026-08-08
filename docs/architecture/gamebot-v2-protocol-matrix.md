# GameBot deployment protocol matrix

This matrix defines the only supported rolling-deployment window for the
Minecraft runtime cutover. Deploy the Node runtime first, then cut Anima over
to v2. Rollback may restore old Python while the dual-surface Node runtime is
deployed; new Python must never run against a v1-only Node runtime.

| Anima client | Node runtime | Supported | Surface | Notes |
|---|---|---:|---|---|
| old Python v1 | dual v1+v2 | yes | `capabilities`, `observe`, `execute_action`, `eval_skill`, `cancel_action`, `health` | Temporary rollback window only. |
| new Python v2 | dual v1+v2 | yes | `gamebot_v2_manifest`, `gamebot_v2_observe`, `gamebot_v2_execute_action`, `gamebot_v2_inspect_region`, `gamebot_v2_inspect_action`, `gamebot_v2_cancel_action`, `gamebot_v2_health` | Production target. Manifest guarantees and schema digest are mandatory. |
| new Python v2 | v1-only | no | none | Startup/readiness fails before command admission. |
| old Python v1 | v2-only | no | none | Allowed only after the Python cutover and rollback window close. |

The v2 namespace never exposes arbitrary-code evaluation or business-mode control.
`gamebot_v2_eval_skill` and `gamebot_v2_set_voyager_mode` return
`UNSUPPORTED_COMMAND`. Correlation identity, single-flight execution, bounded ledger
retention, cancellation acknowledgement, budget enforcement, receipt hash chains,
`inspect_action`, and bounded `inspect_region` are v2 runtime guarantees rather than
client conventions.

The current contract extension also carries discoverable blocks/entities and stable
world identity in observations, typed combat terminal evidence in action receipts,
and canonical `advancement_observed` events. Spectator `following` is a runtime/viewer
projection used as a pre-mission readiness gate; it is not a gameplay capability or
mission-completion signal.

Removal sequence:

1. Deploy the dual-surface Node runtime and verify schema/golden parity.
2. Deploy Anima v2 and require a valid v2 manifest before readiness.
3. Exercise disconnect recovery, `inspect_action` reconciliation, bounded region
   inspection, advancement de-duplication, and spectator-following recovery.
4. Close the rollback window and remove the six v1 command handlers plus the
   v1 production `eval_skill` implementation from Node.
