# July 2026 Release Checklist

- [ ] GPU Docker 完整启动协议通过，health、ready、frontend 均为 HTTP 200。
- [ ] 日志扫描无 Traceback、ERROR、Mock、provider substitution、orphan task。
- [ ] 后端完整 pytest、Ruff、scoped MyPy 通过。
- [ ] 前端 Vitest、Vue typecheck、production build、event validation 通过。
- [ ] 严格 OpenSpec 校验通过，任务与实现一致。
- [ ] 新鲜 Playwright 捕获包含最终文字、Live2D、speaking 或 typed degradation 状态。
- [ ] clean soak 持续至少 600 秒且完成至少 12 轮，p95 text ≤ 8 秒、media ≤ 20 秒。
- [ ] clean soak 无断连、身份错配、重复回答、漂移、marker 泄漏；TTS 降级不超过一次且已恢复。
- [ ] 独立故障演练后已关闭 fault injection 并恢复 golden readiness。
- [ ] 三个 demo 场景和 requirement-to-evidence 矩阵均有当前时间戳证据。
