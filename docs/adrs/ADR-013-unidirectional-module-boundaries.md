# ADR-013: Unidirectional Module Boundaries and Frontend Feature Slices

**Date:** 2026-08-23
**Status:** Accepted

## Context

Animetta's production code grew around technical folders. The backend composition root,
application orchestration and domain services began importing each other, while the Vue
frontend developed cycles between stores, composables, components and contract types.
Large entry files consequently mixed dependency assembly, transport, business policy,
persistence and presentation.

The existing ADRs still bind the design: LangGraph remains the only conversation
orchestrator, providers remain registry-backed, memory remains V2 hybrid storage, and
Socket.IO remains the realtime protocol.

## Decision

Adopt a unidirectional hybrid architecture:

1. `core` is the outer composition root. It may depend on application and domain modules;
   production modules must not import it.
2. `orchestration/server` is a transport adapter and `orchestration/graph` is the
   LangGraph application workflow. Both consume injected protocols rather than concrete
   runtime implementations.
3. `services`, `memory`, `avatar` and `tools` own domain interfaces and implementations;
   they must not import `core` or `orchestration`.
4. `config` contains immutable schemas and resolution only. Runtime reload and service
   lifecycle belong to the composition root.
5. `observability` exposes neutral ports. Product-specific projections are injected.
6. The frontend is organized as `shared` foundations, browser-facing `services`, reactive
   stores/composables, Dashboard presentation, and the framework-independent formal `live`
   entry. Stores do not import composables, contract types do not import UI, and live code
   does not import Dashboard components.
7. A repository architecture audit enforces forbidden edges and package cycles.

Compatibility imports and Socket aliases may exist for one released version, but new
production code must not depend on those facades.

## Consequences

- Runtime ownership, dependency direction and public feature boundaries become explicit.
- Graph nodes and transport handlers become small adapters around independently tested
  services.
- Frontend features can evolve without a global store/composable/component dependency mesh,
  while `/live.html` remains a single lightweight entry.
- Migration requires temporary compatibility facades and coordinated backend/frontend
  changes.
- Adding a cross-module dependency now requires updating an accepted ADR and the
  executable architecture policy rather than silently creating a cycle.

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Full Clean Architecture directory rewrite | Excessive migration and contributor cost for provider-heavy modules already organized by domain. |
| Split only the largest files | Reduces file size without removing dependency cycles or clarifying ownership. |
| Keep architectural rules in documentation only | Cannot prevent regressions during later feature work. |
