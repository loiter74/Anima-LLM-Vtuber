import { createMcpExpressApp } from '@modelcontextprotocol/sdk/server/express.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { readFile } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RuntimeEventBuffer } from './eventBuffer.js';
import { MinecraftLifecycle } from './lifecycle.js';
import { BotRuntimeClient } from './runtimeClient.js';
import { createMcpServer } from './tools.js';

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const stateDir = process.env.MC_MCP_STATE_DIR || path.join(os.tmpdir(), 'animetta-mc-mcp');
const configPath = process.env.MC_MCP_CONFIG || path.join(packageRoot, 'config', 'mc-mcp.json');
const host = process.env.MC_MCP_HOST || '127.0.0.1';
const LOCAL_ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]', 'host.docker.internal'];
const token = process.env.MC_MCP_AUTH_TOKEN;
if (!token) throw new Error('MC_MCP_AUTH_TOKEN is required');
const config = JSON.parse(await readFile(configPath, 'utf8'));
config.root = packageRoot;
const events = new RuntimeEventBuffer(config.event_buffer_capacity ?? 512);
const runtime = new BotRuntimeClient({
  entrypoint: path.join(packageRoot, 'src', 'index.js'),
  cwd: packageRoot,
  eventBuffer: events,
});
const lifecycle = new MinecraftLifecycle({
  config,
  runtime,
  eventBuffer: events,
  stateFile: path.join(stateDir, 'lifecycle.json'),
  managedRegistryFile: process.env.MC_MCP_MANAGED_REGISTRY
    || path.join(os.tmpdir(), 'animetta-mc-mcp', 'managed-projects.json'),
});
await lifecycle.restore();

const app = createMcpExpressApp({ host, allowedHosts: LOCAL_ALLOWED_HOSTS });
const serviceInstanceId = process.env.MC_MCP_SERVICE_INSTANCE_ID ?? null;
app.get('/health', (_req, res) => res.json({
  ok: true,
  service: 'mc-mcp',
  service_instance_id: serviceInstanceId,
  lifecycle: lifecycle.snapshot(),
}));
const authenticate = (req, res, next) => {
  if (req.headers.authorization !== `Bearer ${token}`) {
    res.status(401).json({ error: 'unauthorized' });
    return;
  }
  next();
};
app.use('/mcp', authenticate);
app.post('/mcp', async (req, res) => {
  const server = createMcpServer(lifecycle, runtime, events);
  const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
  res.on('close', () => {
    transport.close();
    server.close();
  });
  try {
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    if (!res.headersSent) res.status(500).json({ error: String(error?.message || error) });
  }
});
app.get('/mcp', (_req, res) => res.status(405).json({ error: 'method_not_allowed' }));
app.delete('/mcp', (_req, res) => res.status(405).json({ error: 'method_not_allowed' }));

const port = Number(process.env.MC_MCP_PORT || 8768);
const httpServer = app.listen(port, host, () => {
  process.stderr.write(`[mc-mcp] listening on http://${host}:${port}/mcp\n`);
});

let closing = false;
async function close() {
  if (closing) return;
  closing = true;
  await runtime.stop();
  httpServer.close(() => process.exit(0));
}
app.post('/service/stop', authenticate, (_req, res) => {
  res.json({ stopped: true, service_instance_id: serviceInstanceId });
  setImmediate(() => void close());
});
process.on('SIGINT', close);
process.on('SIGTERM', close);
