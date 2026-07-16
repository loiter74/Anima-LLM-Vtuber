# Dead-code and duplication audit

Audit date: 2026-07-16

## Scope and commands

- CodeGraph call-path inspection covered Python dynamic registries, CLIs, LangGraph nodes, Qwen engine protocols, Electron preload, Live2D runtime entrypoints, and frontend composables.
- `python -m vulture` now audits `tooling`, `scripts`, `evaluations`, `src/animetta`, and `src/animetta_qwen_tts` at 80% confidence and returns zero findings.
- `pnpm deadcode` runs Knip across the Vue, Electron, and build-script graph and returns zero unused files, exports, types, or dependencies.
- `pnpm duplicates:check` analyzes Vue, TypeScript, JavaScript, HTML, and CSS with a 1% regression threshold. The audited baseline is 0.36% duplicated lines.

## Python classification

| Candidate | Classification | Resolution |
|---|---|---|
| Pydantic validator `cls` parameters | Framework callback contract | Preserved with line-local Vulture suppression |
| `SearchBackend.search(max_results=...)` | Keyword-compatible protocol contract | Preserved with line-local Vulture suppression |
| `QwenEngine.synthesize(**kwargs)` | Provider extension contract | Preserved as `_kwargs` |
| `_enrich_system_prompt` | Deprecated compatibility surface with focused callers | Preserved |
| Benchmark report `traces` parameter | Removable | Removed; trace data remains in the persisted report |
| History smoke `expect_llm` parameter | Removable | Removed; each caller already owns its result assertion |
| Training deploy `character_name` parameter | Removable | Removed; deployment reads the canonical configuration |
| Memory retrieval `max_turns` parameter | Removable | Removed; no recall implementation consumed it |
| Standalone `list(state.get("messages", []))` expression | Removable | Removed as a side-effect-free expression |

## Frontend classification

Dynamic entrypoints retained:

- `electron/preload.cjs`, resolved dynamically by Electron.
- `public/live2d/live2dcubismcore.min.js`, loaded by both HTML entrypoints.
- `useLive2DModel.ts`, treated as the Live2D subsystem API so `centerModel()` remains available under the repository positioning contract.
- `electron-builder-squirrel-windows`, loaded by the Electron packaging toolchain.

Proven unreachable code removed:

- Five orphaned dashboard components superseded by `DashboardPage.vue`.
- The unbuilt `frontend/stats/` prototype page.
- Ten unreferenced Live2D/composable helpers and 22 unused payload/type declarations.
- Two unused direct development dependencies; required transitive packages remain lockfile-managed.

The five remaining clone reports are scoped UI symmetry or component-local presentation blocks: chat list styling, two `InteractivePanel` branches, incoming/outgoing `MemoryGraph` traversal, and the two singing playback surfaces. They remain below the enforced 1% budget; extracting them would couple independent rendering or interaction lifecycles without removing an unreachable implementation.
