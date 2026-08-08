# Minecraft deterministic workflows

The fallback domain owns typed, finite workflow definitions only. It does not
call `MinecraftBridge`, create tasks, or execute persisted code.

The built-in `survival:iron` workflow resolves only an `acquire/iron_ingot`
GoalSpec and proposes bounded `collect`, `craft`, and `smelt` steps. Unsupported
goals fail with `UNSUPPORTED_FALLBACK_GOAL`; fallback evidence never promotes a
learned skill.

Submit it through `mc_execute` with `mode="fallback"`. Inspect progress with
`mc_status` and use `mc_stop` for the durable global stop barrier.
