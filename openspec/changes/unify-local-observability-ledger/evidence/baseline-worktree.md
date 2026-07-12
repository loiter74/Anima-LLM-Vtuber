# Worktree Isolation Baseline

- Captured before observability implementation: `2026-07-12`
- HEAD: `0af42d6e9949e8b577c89c076bcee4b95f4942b4`
- Branch: `main` (also referenced by `codex/harden-live-danmaku-runtime`)
- Pre-existing unrelated dirty path: `AGENTS.md`

The observability implementation must not modify or stage `AGENTS.md`. Voyager/Minecraft work that was dirty during design was committed independently as `60c37ab6` before this implementation baseline and is outside this change.
