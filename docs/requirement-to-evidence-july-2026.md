# July Golden Requirement-to-Evidence Matrix

| 决策 / 里程碑 | 权威证据 |
|---|---|
| D1 产品边界 | `config/animetta.yaml` 的 profile/runtime policy；`docs/scope-2026-07.md` |
| D2 真实 DeepSeek/Qwen Alice | `/ready` 快照；`scripts/smoke_qwen_alice.py`；preflight 测试 |
| D3 固定两次 LLM | `test_dialogue_nodes.py` 调用计数；golden graph 节点清单 |
| D4 四层事件与身份 | `socket-events.json`；contract/real Socket.IO tests；event validator |
| D5 六轮状态/记忆关闭 | conversation session 与 persistence policy tests；readiness/preflight |
| D6 meme 后处理隔离 | golden graph 无 humor/tool 分支；两调用预算测试 |
| M0 基线 | preflight、readiness、Docker contract tests |
| M1 契约 | backend/frontend contract tests；`validate-events.py` |
| M2 人格链 | schema/service/graph/concurrency/persistence tests |
| M3 声画与降级 | delivery/TTS/frontend media tests；Qwen smoke evidence |
| M4 十分钟验收 | `golden-soak-*.json` 的 turns、events、trace、latency、decisions；fresh frontend capture；sanitized log scan |
