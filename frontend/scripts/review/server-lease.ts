import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { promisify } from 'node:util'

const execFileAsync = promisify(execFile)

export function createViteSpawnSpec(
  platform: NodeJS.Platform,
  commandShell = process.env.ComSpec ?? 'cmd.exe',
): { command: string; args: string[] } {
  if (platform === 'win32') {
    return {
      command: commandShell,
      args: ['/d', '/s', '/c', 'pnpm dev --host 127.0.0.1'],
    }
  }
  return {
    command: 'pnpm',
    args: ['dev', '--host', '127.0.0.1'],
  }
}

export interface ServerLeaseOptions {
  baseUrl: string
  probe: (url: URL) => Promise<boolean>
  spawnServer: () => ChildProcessWithoutNullStreams
  terminate: (child: ChildProcessWithoutNullStreams) => Promise<void>
  wait?: () => Promise<void>
  attempts?: number
}

export class ServerLease {
  readonly owned: boolean
  private disposed = false

  private constructor(
    owned: boolean,
    private readonly child: ChildProcessWithoutNullStreams | null,
    private readonly terminate: (child: ChildProcessWithoutNullStreams) => Promise<void>,
  ) {
    this.owned = owned
  }

  static async acquire(_options: ServerLeaseOptions): Promise<ServerLease> {
    const liveUrl = new URL('/live.html', _options.baseUrl)
    if (await _options.probe(liveUrl)) {
      return new ServerLease(false, null, _options.terminate)
    }

    const child = _options.spawnServer()
    const wait =
      _options.wait ??
      (() => new Promise<void>((resolveDelay) => globalThis.setTimeout(resolveDelay, 500)))
    const attempts = _options.attempts ?? 40
    let startupLog = ''
    let exited: string | null = null
    const appendLog = (chunk: Buffer | string): void => {
      startupLog = `${startupLog}${chunk.toString()}`.slice(-8_000)
    }
    child.stdout.on('data', appendLog)
    child.stderr.on('data', appendLog)
    child.once('exit', (code, signal) => {
      exited = `Vite exited before readiness (code=${String(code)}, signal=${String(signal)})`
    })
    child.once('error', (error) => {
      exited = `Vite failed before readiness: ${error.message}`
    })

    try {
      for (let attempt = 0; attempt < attempts; attempt += 1) {
        if (exited) throw new Error(exited)
        if (await _options.probe(liveUrl)) {
          return new ServerLease(true, child, _options.terminate)
        }
        if (attempt < attempts - 1) await wait()
      }
      throw new Error(`Vite did not become ready at ${_options.baseUrl}`)
    } catch (error) {
      await _options.terminate(child).catch(() => {})
      const reason = error instanceof Error ? error.message : String(error)
      throw new Error(`${reason}${startupLog ? `\n${startupLog}` : ''}`, { cause: error })
    }
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    if (this.owned && this.child) await this.terminate(this.child)
  }
}

export async function acquireViteServerLease(
  baseUrl: string,
  frontendDir: string,
): Promise<ServerLease> {
  const probe = async (url: URL): Promise<boolean> => {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2_000) })
      return response.ok
    } catch {
      return false
    }
  }
  const terminate = async (child: ChildProcessWithoutNullStreams): Promise<void> => {
    if (child.exitCode !== null || child.pid === undefined) return
    if (process.platform === 'win32') {
      await execFileAsync('taskkill', ['/PID', String(child.pid), '/T', '/F']).catch(() => {})
      return
    }
    child.kill('SIGTERM')
  }
  return ServerLease.acquire({
    baseUrl,
    probe,
    spawnServer: () => {
      const { command, args } = createViteSpawnSpec(process.platform)
      return spawn(command, args, {
        cwd: frontendDir,
        env: { ...process.env },
        stdio: ['pipe', 'pipe', 'pipe'],
        windowsHide: true,
      })
    },
    terminate,
  })
}
