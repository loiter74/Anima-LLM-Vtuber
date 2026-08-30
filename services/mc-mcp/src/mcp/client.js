import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';

export const DEFAULT_MCP_REQUEST_TIMEOUT_MS = 60_000;
export const DEFAULT_MCP_PREPARE_TIMEOUT_MS = 180_000;

export function resolveRequestTimeoutMs(value = process.env.MC_MCP_REQUEST_TIMEOUT_MS) {
  if (value === undefined || value === '') return DEFAULT_MCP_REQUEST_TIMEOUT_MS;
  const timeoutMs = Number(value);
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) throw new Error('INVALID_MC_MCP_REQUEST_TIMEOUT_MS');
  return timeoutMs;
}

export async function callMcpTool(
  descriptor,
  name,
  args = {},
  { timeoutMs = resolveRequestTimeoutMs() } = {},
) {
  const client = new Client({ name: 'mc-mcp-cli', version: '1.0.0' });
  const transport = new StreamableHTTPClientTransport(new URL(descriptor.url), {
    requestInit: { headers: { Authorization: `Bearer ${descriptor.token}` } },
  });
  await client.connect(transport);
  try {
    const result = await client.callTool(
      { name, arguments: args },
      undefined,
      { timeout: timeoutMs, maxTotalTimeout: timeoutMs },
    );
    return decodeToolResult(result, name);
  } finally {
    await transport.close();
  }
}

export function decodeToolResult(result, toolName = 'MCP tool') {
  const text = result.content?.find((item) => item.type === 'text')?.text;
  let value = result.structuredContent;
  if (value === undefined && text !== undefined) {
    try {
      value = JSON.parse(text);
    } catch {
      value = text;
    }
  }
  if (result.isError) {
    const detail = value?.error ?? value;
    const message = typeof detail === 'string'
      ? detail
      : (detail?.message ?? detail?.code ?? `${toolName} failed`);
    const error = new Error(message);
    if (detail && typeof detail === 'object' && detail.code) error.code = detail.code;
    throw error;
  }
  return value ?? null;
}
