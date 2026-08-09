# Minecraft deterministic workflows

The fallback domain owns typed, finite workflow definitions only. It does not
call the MCP bridge directly, create tasks, or execute persisted code.

The built-in `survival:iron` workflow resolves only an `acquire/iron_ingot`
GoalSpec and proposes bounded `collect`, `craft`, and `smelt` steps. Unsupported
goals fail with `UNSUPPORTED_FALLBACK_GOAL`; fallback evidence never promotes a
learned skill.

Submit it through `mc_operate_bot` with `operation="execute"` and fallback mode.
Inspect progress with `operation="progress"` and use `operation="cancel"` for the
durable global stop barrier.
