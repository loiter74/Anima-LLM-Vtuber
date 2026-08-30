# mc-mcp 服务智能体指南

`services/mc-mcp/` 是 Animetta 仓库内独立部署、独立进程运行的 Node.js/Mineflayer 服务。它拥有 Minecraft 服务端、bot、viewer controller 与 GameBot v2 runtime 的生命周期；Python 侧只通过 loopback Streamable HTTP MCP 调用它。

## 边界

- 对外 MCP 生命周期与 GameBot v2 工具保持向后兼容；不得把 Mineflayer 对象、任意代码执行或旧版细粒度动作暴露给 Animetta。
- `contracts/gamebot/v2/` 根目录是唯一协议真相源；服务测试直接读取根契约，不在本目录维护副本。
- `external-local` 是默认 profile。普通开发和测试不得创建或停止现有 Minecraft 服务端；managed profile 仍需显式 `allow_create`。
- 服务、bot 与 managed server 的持久化身份必须继续由 mc-mcp 自己校验；`disconnect` 只停 bot，`shutdown` 只停当前服务拥有的 managed 资源。

## Node.js

- 使用 ESM 与项目锁定的 `package-lock.json`，不得提交 `node_modules/`、临时状态或运行日志。
- 新增职责优先拆成纯函数、协议适配、生命周期或 Mineflayer 动作模块，避免继续扩大 `src/index.js`；该入口逐步只保留组装与进程协议。
- 用户可见 MCP 描述与错误信息使用中文；代码符号和运行日志使用英文。

## 验证

- 目标测试：`npm test --prefix services/mc-mcp -- <测试文件...>`。
- 完整服务验证：`npm run check --prefix services/mc-mcp` 与 `npm test --prefix services/mc-mcp`。
- 不启动 Docker 或真实 Minecraft，除非用户明确要求运行时验收。
