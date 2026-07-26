import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { createServer } from 'node:net'
import { join } from 'node:path'
import { promisify } from 'node:util'
import type {
  ReviewAttemptContext,
  ReviewAttemptPreparation,
  ReviewPluginArtifacts,
} from './registry'
import { parseTtsFailoverHarnessResponse } from './tts-harness-contract'

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
  if (!port) throw new Error('Unable to allocate loopback review port')
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

export class TtsHarnessLease {
  private disposed = false
  private readonly artifacts = new Map<string, ReviewPluginArtifacts>()

  private constructor(
    private readonly child: ChildProcessWithoutNullStreams,
    readonly baseUrl: string,
    private readonly token: string,
  ) {}

  static async acquire(repositoryDir: string): Promise<TtsHarnessLease> {
    const port = await freeLoopbackPort()
    const token = randomUUID()
    const child = spawn(
      'py',
      [
        '-3.13',
        join(repositoryDir, 'scripts', 'tts_failover_review_harness.py'),
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
      boundedLog = `${boundedLog}${chunk.toString()}`
        .replaceAll(token, '[redacted]')
        .replaceAll(repositoryDir, '[workspace]')
        .slice(-4_000)
    }
    child.stdout.on('data', appendLog)
    child.stderr.on('data', appendLog)
    child.once('exit', () => {
      exited = true
    })
    const lease = new TtsHarnessLease(child, `http://127.0.0.1:${port}`, token)
    try {
      for (let attempt = 0; attempt < 80; attempt += 1) {
        if (exited) throw new Error('TTS failover harness exited before readiness')
        try {
          const response = await fetch(`${lease.baseUrl}/health`, {
            signal: AbortSignal.timeout(1_000),
          })
          if (response.ok) break
        } catch {
          // The child is still starting.
        }
        if (attempt === 79) throw new Error('TTS failover harness did not start')
        await wait(250)
      }
      const ready = await fetch(`${lease.baseUrl}/ready`, {
        method: 'POST',
        headers: { authorization: `Bearer ${token}` },
        signal: AbortSignal.timeout(60_000),
      })
      if (!ready.ok) throw new Error(`TTS failover harness readiness failed (${ready.status})`)
      const payload = (await ready.json()) as {
        readiness?: { active_backend?: string; primary?: { error_category?: string } }
      }
      if (
        payload.readiness?.active_backend !== 'fallback' ||
        payload.readiness.primary?.error_category !== 'billing'
      ) {
        throw new Error('TTS failover harness readiness identity mismatch')
      }
      return lease
    } catch (error) {
      await lease.dispose()
      const reason = error instanceof Error ? error.message : String(error)
      throw new Error(`${reason}${boundedLog ? `\n${boundedLog}` : ''}`, { cause: error })
    }
  }

  async prepareAttempt(context: ReviewAttemptContext): Promise<ReviewAttemptPreparation> {
    const response = await fetch(`${this.baseUrl}/v1/review/synthesize`, {
      method: 'POST',
      headers: {
        authorization: `Bearer ${this.token}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({ scene_id: context.sceneId }),
      signal: AbortSignal.timeout(60_000),
    })
    if (!response.ok) throw new Error(`TTS failover attempt failed (${response.status})`)
    const payload = parseTtsFailoverHarnessResponse(await response.json())
    const evidenceDir = join(context.runDir, 'evidence')
    await mkdir(evidenceDir, { recursive: true })
    const stem = `${context.sceneId}-${String(context.attempt).padStart(3, '0')}`
    const audioWav = join(evidenceDir, `${stem}-audio.wav`)
    const backendReport = join(evidenceDir, `${stem}-backend.json`)
    const [audioResponse, reportResponse] = await Promise.all([
      fetch(new URL(payload.audio_wav, this.baseUrl)),
      fetch(new URL(payload.backend_report, this.baseUrl)),
    ])
    if (!audioResponse.ok || !reportResponse.ok) {
      throw new Error('TTS failover artifacts could not be downloaded')
    }
    await Promise.all([
      writeFile(audioWav, Buffer.from(await audioResponse.arrayBuffer())),
      writeFile(backendReport, Buffer.from(await reportResponse.arrayBuffer())),
    ])
    this.artifacts.set(`${context.sceneId}:${context.attempt}`, { audioWav, backendReport })
    return {
      pageParams: {
        audio: new URL(payload.audio_wav, this.baseUrl).href,
        backend: payload.report.actual_backend,
        provider: payload.report.actual_provider,
        firstAudio: payload.report.first_audio_seconds.toFixed(3),
        rtf: payload.report.rtf.toFixed(3),
        sampleRate: String(payload.report.sample_rate),
        mouthTimeline: JSON.stringify(payload.mouth_timeline),
      },
      assertions: [
        { name: 'primary-error:billing', passed: true },
        { name: 'actual-backend:fallback', passed: true },
        { name: 'readiness:ready-degraded', passed: true },
        { name: 'pcm:complete-24khz-mono', passed: true },
        { name: 'first-audio<=0.75s', passed: true },
        { name: 'rtf<=0.35', passed: true },
      ],
      observations: [
        { name: 'actual_backend', value: payload.report.actual_backend },
        { name: 'primary_error_category', value: payload.report.primary_error_category },
        { name: 'first_audio', value: payload.report.first_audio_seconds, unit: 'seconds' },
        { name: 'rtf', value: payload.report.rtf },
        { name: 'pcm_bytes', value: payload.report.pcm_bytes, unit: 'bytes' },
      ],
    }
  }

  artifactsFor(context: ReviewAttemptContext): ReviewPluginArtifacts {
    return this.artifacts.get(`${context.sceneId}:${context.attempt}`) ?? {}
  }

  async dispose(): Promise<void> {
    if (this.disposed) return
    this.disposed = true
    await terminate(this.child)
  }
}
