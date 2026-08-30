import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import {
  DEFAULT_MCP_REQUEST_TIMEOUT_MS,
  DEFAULT_MCP_PREPARE_TIMEOUT_MS,
  decodeToolResult,
  resolveRequestTimeoutMs,
} from '../src/mcp/client.js';

describe('mc-mcp client result decoding', () => {
  it('preserves a plain-text MCP error instead of masking it as invalid JSON', () => {
    assert.throws(
      () => decodeToolResult({
        isError: true,
        content: [{ type: 'text', text: 'RUNTIME_EVENT_TIMEOUT' }],
      }, 'minecraft_connect'),
      /RUNTIME_EVENT_TIMEOUT/,
    );
  });

  it('uses structured error codes and returns structured success values', () => {
    assert.throws(
      () => decodeToolResult({
        isError: true,
        structuredContent: { error: { code: 'SERVER_UNAVAILABLE' } },
      }),
      (error) => error.message === 'SERVER_UNAVAILABLE' && error.code === 'SERVER_UNAVAILABLE',
    );
    assert.deepEqual(
      decodeToolResult({ structuredContent: { state: 'ready' } }),
      { state: 'ready' },
    );
  });

  it('enforces the one-minute command-to-ready SLO', () => {
    assert.equal(DEFAULT_MCP_REQUEST_TIMEOUT_MS, 60_000);
    assert.equal(DEFAULT_MCP_PREPARE_TIMEOUT_MS, 180_000);
    assert.equal(resolveRequestTimeoutMs(), 60_000);
    assert.equal(resolveRequestTimeoutMs('45000'), 45_000);
    assert.throws(() => resolveRequestTimeoutMs('invalid'), /INVALID_MC_MCP_REQUEST_TIMEOUT_MS/);
  });
});
