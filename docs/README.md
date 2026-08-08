# 📚 Animetta Documentation

> Documentation navigation index. For project entry and quick start, see the [root README](../README.md).

## Architecture & Design

| Document | Description |
|----------|-------------|
| [architecture/overview.md](architecture/overview.md) | C4 diagrams, LangGraph flow, core components |
| [architecture/patterns.md](architecture/patterns.md) | Design patterns applied in the codebase |
| [adrs/](adrs/) | 13 Architecture Decision Records |

## Development Guides

| Document | Description |
|----------|-------------|
| [development/testing.md](development/testing.md) | pytest conventions, layers, coverage targets |
| [development/minecraft-bot-architecture.md](development/minecraft-bot-architecture.md) | MC bot: Python bridge, Node Mineflayer, Voyager skills, survival loop |
| [development/ai-ui-workflow.md](development/ai-ui-workflow.md) | Asking AI to optimize UI using the design system |
| [development/runtime-config-reload.md](development/runtime-config-reload.md) | Hot-reload runtime config |
| [development/deployment.md](development/deployment.md) | Deployment modes (one-click / free-tier / mock) |
| [development/streaming-interaction-patterns.md](development/streaming-interaction-patterns.md) | Livestream engagement patterns |
| [development/project-health.md](development/project-health.md) | Project health contract, status model, debt backlog |
| [development/health-advisories.md](development/health-advisories.md) | Known slow / exploratory / staged health checks |
| [development/gpt-sovits-rtx5090-setup.md](development/gpt-sovits-rtx5090-setup.md) | GPT-SoVITS on RTX 5090 / WSL2 |
| [development/rvc-training-guide.md](development/rvc-training-guide.md) | RVC WebUI voice training |

## Reference

| Document | Description |
|----------|-------------|
| [reference/backend-api.md](reference/backend-api.md) | HTTP REST + Socket.IO API reference |
| [reference/socket-api.md](reference/socket-api.md) | Frontend ↔ backend Socket.IO event catalog |
| [reference/tools.md](reference/tools.md) | Tool system: built-in tools, MCP config, LangGraph integration |
| [reference/rag-evaluation-report.md](reference/rag-evaluation-report.md) | RAG retrieval evaluation results |

## Deployment

| Document | Description |
|----------|-------------|
| [deployment/docker.md](deployment/docker.md) | Docker Compose GPU/CPU deployment |
| [deployment/zeabur.md](deployment/zeabur.md) | Zeabur platform deployment |

## Project Governance

| Document | Description |
|----------|-------------|
| [roadmap.md](roadmap.md) | Monthly roadmap |
| [risk-log.md](risk-log.md) | Risk register |
| [scope-2026-07.md](scope-2026-07.md) | July 2026 scope |
| [runbooks/july-golden-demo.md](runbooks/july-golden-demo.md) | Ops runbook for the July golden demo |
| [retrospective/2026-07.md](retrospective/2026-07.md) | July monthly review |

## Demos

| Document | Description |
|----------|-------------|
| [demo/interview-demo.md](demo/interview-demo.md) | Interview demo walkthrough |
| [demo/interview-qa.md](demo/interview-qa.md) | Interview Q&A prep |

## Change Tracking

New changes go through the [openspec](../openspec/) spec-driven system — run `/opsx-propose` to start a change.

## Minecraft

| Document | Description |
|----------|-------------|
| [minecraft/client-viewer.md](minecraft/client-viewer.md) | Real MC client viewer / spectate / OBS capture |
