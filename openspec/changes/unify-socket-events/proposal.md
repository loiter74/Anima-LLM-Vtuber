## Why

Animetta 的 Socket.IO 事件命名存在三种混用格式：下划线 (`text_input`)、点分隔 (`bilibili.connect`)、冒号分隔 (`sing:process`)。48 个唯一事件分布在 15+ 个前端文件中。这种不一致性增加了开发者记忆负担，新事件不知道用哪种格式，且无法从事件名推断模块归属。统一命名规范是提升代码可维护性的基础工作。

## What Changes

- 将所有 48 个 Socket.IO 事件统一为点分隔格式 `{module}.{action}`
- 创建 `config/socket-events.json` 作为单一真相源
- 前后端都从 JSON 读取事件名
- **不保留向后兼容层**，全量迁移一次交付
- 更新所有前端 `socket.emit()` / `socket.on()` 调用（15 个文件）
- 更新后端 `routes.py` 事件注册（10 个文件）
- 添加 CI/CD 验证脚本（Docker 构建时）
- 编写自动化测试 + E2E 测试

### 命名规范

- **发送类事件**（客户端→服务器）：无动词，如 `chat.text`
- **接收类事件**（服务器→客户端）：结果名词，如 `chat.sentence`

### 命名映射示例

| 旧格式 | 新格式 |
|--------|--------|
| `text_input` | `chat.text` |
| `sing:process` | `sing.process` |
| `bilibili.connect` | `bilibili.connect` (不变) |

## Capabilities

### New Capabilities

- `event-constants`: JSON 配置文件定义所有 Socket.IO 事件名，前后端共享
- `event-validation`: CI/CD 验证脚本，确保事件名一致性

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

### 受影响代码

- `config/socket-events.json` - 新建，事件名定义
- `frontend/src/constants/socket-events.ts` - 新建，TypeScript 类型
- `scripts/validate-events.py` - 新建，验证脚本
- `src/animetta/orchestration/server/routes.py` - 后端事件注册（29 个事件）
- `frontend/src/composables/*.ts` - 前端事件调用（useChat, useVoice, useSinging 等）
- `frontend/src/stores/*.ts` - Pinia store 中的事件调用
- `frontend/src/components/*.vue` - Vue 组件中的事件调用

### 依赖

- 无新依赖

### 风险

- **低风险**: 全量迁移，前后端需同时部署
- 需要自动化测试确保不遗漏事件
