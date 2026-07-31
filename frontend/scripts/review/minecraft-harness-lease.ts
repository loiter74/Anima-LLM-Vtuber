import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { promisify } from 'node:util'
import { MinecraftReviewClient } from './minecraft-review-client'

const execFileAsync = promisify(execFile)

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs))
}

async function freeLoopbackPort(): Promise<number> {
  const server = createServer()
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject)
    server.listen(0, '127.0.0.1', resolve)
  })
  const address = server.address()
  const port = address && typeof address === 'object' ? address.port : 0
  await new Promise<void>((resolve, reject) =>
    server.close((error) => (error ? reject(error) : resolve())),
  )
  if (!port) throw new Error('Unable to allocate Minecraft review port')
  return port
}

async function terminate(child: ChildProcessWithoutNullStreams): Promise<void> {
  if (child.exitCode !== null || child.pid === undefined) return
  if (process.platform === 'win32') {
    await execFileAsync('taskkill', ['/PID', String(child.pid), '/T', '/F']).catch(() => {})
    return
  }
  child.kill('SIGTERM')
}

export class MinecraftHarnessLease {
  private disposed = false

  private constructor(
    private readonly child: ChildProcessWithoutNullStreams,
    readonly client: MinecraftReviewClient,
  ) {}

  static async acquire(repositoryDir: string): Promise<MinecraftHarnessLease> {
    const port = await freeLoopbackPort()
    const token = randomUUID()
    const baseUrl = `http://127.0.0.1:${port}`
    const child = spawn(
      'py',
      [
        '-3.13',
        join(repositoryDir, 'scripts', 'minecraft_gameplay_review_harness.py'),
        '--port',
        String(port),
      ],
      {
        cwd: repositoryDir,
        env: {
          ...process.env,
          ANIMETTA_REVIEW_TOKEN: token,
          PYTHONPATH: join(repositoryDir, 'src'),
        },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      },
    )
    let exited = false
    let boundedLog = ''
    const appendLog = (chunk: Buffer | string): void => {
      const sanitized = chunk
        .toString()
        .replaceAll(token, '[redacted]')
        .replaceAll(repositoryDir, '[workspace]')
      boundedLog = `${boundedLog}${sanitized}`.slice(-4_000)
      if (process.env.COLLECT_DEBUG) process.stderr.write(sanitized)
    }
    child.stdout.on('data', appendLog)
    child.stderr.on('data', appendLog)
    child.once('exit', () => {
      exited = true
    })
    const lease = new MinecraftHarnessLease(child, new MinecraftReviewClient(baseUrl, token))
    try {
      for (let attempt = 0; attempt < 80; attempt += 1) {
        if (exited) throw new Error('Minecraft review harness exited before readiness')
        try {
          const response = await fetch(`${baseUrl}/health`, {
            signal: AbortSignal.timeout(1_000),
          })
          if (response.ok) break
        } catch {
          // Harness process is still starting.
        }
        if (attempt === 79) throw new Error('Minecraft review harness did not start')
        await wait(250)
      }
      await lease.client.assertReady()
      return lease
    } catch (error) {
      await lease.dispose()
      const reason = error instanceof Error ? error.message : String(error)
      throw new Error(`${reason}${boundedLog ? `\n${boundedLog}` : ''}`, { cause: error })
    }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    await this.client.close()
    await terminate(this.child)
  }
}
