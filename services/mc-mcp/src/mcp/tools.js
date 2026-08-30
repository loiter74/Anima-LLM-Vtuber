import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as z from 'zod/v4';

import { actionTimeoutFromDeadline } from '../actionDeadline.js';

const requestId = z.string().min(1).max(128);
const payload = z.record(z.string(), z.unknown()).default({});

function toolResult(value) {
  const structuredContent = value && typeof value === 'object' && !Array.isArray(value)
    ? value
    : { value };
  return {
    content: [{ type: 'text', text: JSON.stringify(value) }],
    structuredContent,
  };
}

function runtimeResult(response) {
  if (response?.status !== 'success') {
    const error = response?.result ?? { code: 'RUNTIME_ERROR', message: 'Runtime command failed' };
    return {
      isError: true,
      content: [{ type: 'text', text: JSON.stringify(error) }],
      structuredContent: { ok: false, error },
    };
  }
  return toolResult(response.result);
}

export function createMcpServer(lifecycle, runtime, eventBuffer) {
  const server = new McpServer({ name: 'mc-mcp', version: '1.0.0' });
  server.registerTool('minecraft_connect', {
    description: '连接一个由 mc-mcp 配置的托管或外部 Minecraft profile。',
    inputSchema: {
      profile: z.string().min(1),
      request_id: requestId,
      allow_create: z.boolean().default(false),
    },
  }, async ({ profile, request_id, allow_create }) => toolResult(
    await lifecycle.connect(profile, request_id, allow_create),
  ));
  server.registerTool('minecraft_prepare', {
    description: '在目标指令到来前准备托管 Minecraft 服务端，不启动 bot。',
    inputSchema: {
      profile: z.string().min(1),
      request_id: requestId,
      allow_create: z.boolean().default(false),
    },
  }, async ({ profile, request_id, allow_create }) => toolResult(
    await lifecycle.prepare(profile, request_id, allow_create),
  ));
  server.registerTool('minecraft_connection_status', {
    description: '读取 Minecraft 服务端、bot 与 viewer 的权威生命周期状态。',
  }, async () => toolResult(lifecycle.snapshot()));
  server.registerTool('minecraft_disconnect', {
    description: '断开 bot，但保留 mc-mcp 拥有的托管 Minecraft 服务端。',
    inputSchema: { request_id: requestId },
  }, async ({ request_id }) => toolResult(await lifecycle.disconnect(request_id)));
  server.registerTool('minecraft_shutdown', {
    description: '停止 bot，并仅关闭 mc-mcp 自己拥有的托管 Minecraft 服务端。',
    inputSchema: { request_id: requestId },
  }, async ({ request_id }) => toolResult(await lifecycle.shutdown(request_id)));
  server.registerTool('minecraft_reattach_viewer', {
    description: '请求 bot 的 viewer controller 重新执行观察账号附身。',
    inputSchema: { request_id: requestId },
  }, async ({ request_id }) => toolResult(await lifecycle.reattachViewer(request_id)));
  server.registerTool('minecraft_managed_setup', {
    description: '仅对 mc-mcp 自有托管服务器执行封闭白名单内的验收场景设置命令。',
    inputSchema: { request_id: requestId, command: z.string().min(1).max(512) },
  }, async ({ request_id, command }) => toolResult(
    await lifecycle.runManagedSetup(command, request_id),
  ));

  const runtimeTools = {
    gamebot_manifest: ['gamebot_v2_manifest', 5_000],
    gamebot_observe: ['gamebot_v2_observe', 5_000],
    gamebot_execute_action: ['gamebot_v2_execute_action', actionTimeoutFromDeadline],
    gamebot_inspect_region: ['gamebot_v2_inspect_region', 10_000],
    gamebot_inspect_action: ['gamebot_v2_inspect_action', 5_000],
    gamebot_cancel_action: ['gamebot_v2_cancel_action', 10_000],
    gamebot_health: ['gamebot_v2_health', 5_000],
    review_survival_iron: ['survival_iron', 2_130_000],
  };
  for (const [name, [action, timeoutPolicy]] of Object.entries(runtimeTools)) {
    server.registerTool(name, {
      description: `调用已连接 bot 的 ${action} 能力。`,
      inputSchema: { payload },
    }, async ({ payload: args }) => {
      const timeoutMs = typeof timeoutPolicy === 'function'
        ? timeoutPolicy(args.deadline_ms)
        : timeoutPolicy;
      return runtimeResult(await runtime.send(action, args, timeoutMs));
    });
  }
  server.registerTool('gamebot_events_since', {
    description: '按 cursor 读取 runtime、viewer 与 advancement 事件。',
    inputSchema: {
      cursor: z.number().int().min(0).default(0),
      limit: z.number().int().min(1).max(500).default(100),
    },
  }, async ({ cursor, limit }) => toolResult(eventBuffer.listAfter(cursor, limit)));
  return server;
}
