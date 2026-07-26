## 1. Shared Review Contracts and Livestream Plugin

- [x] 1.1 Add failing tests for catalog-derived IDs, ordering, URL fallback, common timeline prefixes, and frozen fixture copy
- [x] 1.2 Implement browser-safe review contracts, timeline player, disposer stack, and static plugin registry
- [x] 1.3 Move the eight livestream scenes into one typed catalog and retain compatibility exports

## 2. Page Lifecycle and Layout Cleanup

- [x] 2.1 Add failing tests for listener-before-start ordering and idempotent full disposal
- [x] 2.2 Refactor the live page into an explicit disposable session
- [x] 2.3 Remove unreachable danmaku collapse APIs while preserving the approved layout

## 3. TypeScript Runner and Evidence v2

- [x] 3.1 Add failing tests for automatic/interactive policies, immutable v2 attempts, artifact validation, semantic fingerprints, and stable rounds
- [x] 3.2 Implement the generic orchestrator, atomic evidence store, v1 reader, and validated stable-round computation
- [x] 3.3 Add failing tests and implement owned/external `ServerLease`, bounded logs, signals, and process-tree cleanup
- [x] 3.4 Add failing protocol tests and implement OBS WebSocket setup, capture, synchronization, and restoration
- [x] 3.5 Add Playwright structural assertions, fresh contexts, final evidence capture, and late-error collection

## 4. Migration and Quality Integration

- [x] 4.1 Add the generic `pnpm review` command and retain `pnpm live:review`
- [x] 4.2 Migrate MJS tests to TypeScript/Vitest and remove superseded MJS implementation after parity
- [x] 4.3 Add Node TypeScript checking and include review tests in the canonical frontend quality groups

## 5. Verification and Freeze

- [x] 5.1 Run focused and full frontend tests, review typecheck, lint, and production build
- [x] 5.2 Run fresh Playwright capture for all eight scenes and verify no production Socket.IO request
- [x] 5.3 Validate OpenSpec artifacts, `make quality-validate`, and `make test-affected`
- [x] 5.4 Run the Docker startup protocol through a dedicated sub-agent
- [x] 5.5 Execute two consecutive automatic OBS-backed full-profile runs and verify stable-round count two
