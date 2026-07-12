# FRONTEND — VUE 3 + ELECTRON + LIVE2D

**Generated:** 2026-05-31
**Commit:** cdd4a87

> Parent: [../AGENTS.md](../AGENTS.md) — root project conventions.

## OVERVIEW

Vue 3 + TypeScript Electron desktop application with Live2D avatar rendering, chat UI, and settings dashboard. Uses UnoCSS, Pinia, pixi-live2d-display.

## STRUCTURE

```
frontend/
├── src/
│   ├── main.ts              # Vue app entry + router + Pinia
│   ├── App.vue              # Root component
│   ├── components/          # UI components
│   │   ├── chat/            # Chat interface (bubbles, input, streaming)
│   │   ├── dashboard/       # Stats widgets, charts
│   │   ├── layout/          # App layout (sidebar, panels)
│   │   ├── live2d/          # Live2D canvas + model management
│   │   ├── meme/            # MemeCard, meme display
│   │   ├── memory/          # MemoryPanel, knowledge browsing
│   │   ├── personality/     # PersonalityPanel, persona config
│   │   ├── shared/          # Shared UI primitives
│   │   └── singing/         # MusicCard, PlaybackControls, WaveformDisplay
│   ├── composables/         # Vue composables (reusable logic)
│   ├── stores/              # Pinia state stores
│   ├── views/               # Route-level views
│   ├── router/              # Vue Router config
│   ├── types/               # TypeScript type definitions
│   └── styles/              # Global styles
├── index.html               # HTML entry
├── package.json              # Dependencies + scripts
├── tsconfig.json             # TypeScript config
├── vite.config.ts            # Vite build config
├── vitest.config.ts          # Vitest + happy-dom test config
└── uno.config.ts             # UnoCSS config
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| Chat UI | `src/components/chat/` | Message bubbles, input, streaming display |
| Dashboard stats | `src/components/dashboard/` | Stats widgets, usage charts |
| Live2D rendering | `src/components/live2d/useLive2D.ts` | Model loading, scaling, expression control |
| Live2D viseme sync | `src/components/live2d/` | Audio-driven mouth shape matching |
| Memory panel | `src/components/memory/` | Memory browsing, search results |
| Singing UI | `src/components/singing/` | MusicCard, PlaybackControls, WaveformDisplay |
| State management | `src/stores/` | 11 Pinia stores (chat, settings, live2d, stats, etc.) |
| Settings panel | `src/views/` or `src/components/` | Provider selection, persona config |
| Subtitle overlay | `src/components/live2d/` | Bilingual subtitle rendering |

## KEY PATTERNS

- **Composition API**: All components use `<script setup lang="ts">`
- **Pinia stores**: Reactive state, no Vuex
- **UnoCSS**: Utility-first CSS, configured in `uno.config.ts`
- **pixi-live2d-display**: Live2D rendering via PixiJS

## CRITICAL CONSTRAINTS

### Live2D (`useLive2D.ts`)
- **NEVER use `getBounds()` in real-time scaling** — creates feedback loop. Always use cached `baseBounds`.
- **Do NOT reset `model.x`/`model.y`/`anchor` in `applyScale()`** — position managed by drag interaction.
- **`handleResize()` does NOT re-center** — preserves user's drag offset. Does NOT change scale.
- **Expression control**: Expressions auto-clear after duration. Idle motion loops independently.

### Electron
- **Main process vs renderer**: Electron main process handles window management, renderer handles UI.
- **IPC**: Use Electron IPC for main↔renderer communication.
- **Build status**: Electron builder not yet configured — runs as Vite dev server (port 3000). No `electron.vite.config.ts` on disk.

## STYLE CONVENTIONS

- **UnoCSS first**: All new components use UnoCSS utility classes. CSS variables (`var(--c-*)`) are reserved as token definitions (in `themes.css`), not for direct use in component `<style>` blocks.
- **Style reference**: See `STYLE_GUIDE.md` for the complete CSS variable → UnoCSS mapping table, component template, and code review checklist.
- **No new hex colors**: Always use design tokens (`text-c-accent`, not `color: #e879a8`).
- **Rounded corners**: Default is `rounded-xl` (12px). No 90-degree corners except the window itself.
- **Motion**: Use `duration-150` (fast), `duration-200` (base), or `duration-300` (slow). Max 300ms.

## ANTI-PATTERNS

- ❌ Never mutate Live2D model position directly — use `centerModel()` only
- ❌ Never call live `getBounds()` in render/animation loops
- ❌ No Direct DOM manipulation — use Vue reactivity
- ❌ No `@ts-ignore` or `as any` type suppressions

## COMMANDS

```bash
cd frontend && pnpm install  # Install
pnpm dev                     # Dev server (port 3000)
pnpm build                   # Build
pnpm vue-tsc --noEmit        # Type check
pnpm test:run                # Frontend tests (Vitest + happy-dom)
```

## NOTES

- **31 Vitest test files exist** under `src/` — use `pnpm test:run` for the happy-dom suite.
- Live2D model files (`.moc3`, textures) are loaded from `assets/` at runtime.
- Bilingual subtitle feature uses LLM translation — configured in Settings panel.
- **Dev server runs on port 3000** (Vite, not 5173). Electron builder is not configured.
