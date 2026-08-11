import { spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { chromium, type Page } from 'playwright'
import { io, type Socket } from 'socket.io-client'

interface Options {
  baseUrl: string
  audioFile: string
  lyrics: string
  durationSeconds: number
  timeoutMs: number
  headed: boolean
  output?: string
  expectedProvider: string
  expectedModel: string
  expectedRevision: string
  expectedVoice: string
}

interface PlaybackEvidence {
  count: number
  taskId: string
  state: string
  kind: string
}

function parseArgs(argv: string[]): Options {
  const values = new Map<string, string>()
  const flags = new Set<string>()
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index]
    if (!token.startsWith('--')) throw new Error(`Unexpected argument: ${token}`)
    if (token === '--headed') {
      flags.add(token)
      continue
    }
    const value = argv[index + 1]
    if (!value || value.startsWith('--')) throw new Error(`Missing value for ${token}`)
    values.set(token, value)
    index += 1
  }
  const audioFile = values.get('--audio-file')
  if (!audioFile) throw new Error('--audio-file is required')
  return {
    baseUrl: values.get('--base-url') ?? 'http://127.0.0.1',
    audioFile: resolve(audioFile),
    lyrics: values.get('--lyrics') ?? '啦啦啦，直播唱歌链路测试。',
    durationSeconds: Number(values.get('--duration-seconds') ?? '12'),
    timeoutMs: Number(values.get('--timeout-seconds') ?? '300') * 1000,
    headed: flags.has('--headed'),
    output: values.get('--output'),
    expectedProvider: values.get('--expected-provider') ?? 'rvc-webui-host',
    expectedModel: values.get('--expected-model') ?? 'shige_utage.pth',
    expectedRevision:
      values.get('--expected-revision') ??
      'f8e22f8ca45a8855ef0deb331ebc8c9d7f19176d030beaabab4271065e791843',
    expectedVoice: values.get('--expected-voice') ?? 'shige_utage',
  }
}

function playbackEvidence(page: Page): Promise<PlaybackEvidence> {
  return page.locator('#audioStatus').evaluate((element) => ({
    count: Number((element as HTMLElement).dataset.playbackCount ?? 0),
    taskId: (element as HTMLElement).dataset.lastAudioTaskId ?? '',
    state: (element as HTMLElement).dataset.playbackState ?? '',
    kind: (element as HTMLElement).dataset.lastAudioKind ?? '',
  }))
}

async function waitForSocket(socket: Socket, timeoutMs: number): Promise<void> {
  if (socket.connected) return
  await new Promise<void>((resolveConnection, rejectConnection) => {
    const timer = setTimeout(
      () => rejectConnection(new Error('Socket.IO connection timed out')),
      timeoutMs,
    )
    socket.once('connect', () => {
      clearTimeout(timer)
      resolveConnection()
    })
    socket.once('connect_error', (error) => {
      clearTimeout(timer)
      rejectConnection(error)
    })
  })
}

async function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  try {
    return await Promise.race([
      promise,
      new Promise<T>((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label} timed out after ${timeoutMs}ms`)),
          timeoutMs,
        )
      }),
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

async function main(): Promise<void> {
  const options = parseArgs(process.argv.slice(2))
  const taskId = `sing-${randomUUID()}`
  const temporary = await mkdtemp(join(tmpdir(), 'animetta-live-singing-'))
  const preparedAudio = join(temporary, `${taskId}.wav`)
  const ffmpeg = spawnSync(
    'ffmpeg',
    [
      '-hide_banner',
      '-loglevel',
      'error',
      '-i',
      options.audioFile,
      '-t',
      String(options.durationSeconds),
      '-vn',
      '-ac',
      '2',
      '-ar',
      '44100',
      '-y',
      preparedAudio,
    ],
    { encoding: 'utf8' },
  )
  if (ffmpeg.status !== 0) {
    throw new Error(`ffmpeg input preparation failed: ${ffmpeg.stderr.trim()}`)
  }

  const browser = await chromium.launch({
    headless: !options.headed,
  })
  const trigger = io(options.baseUrl, {
    path: '/socket.io/',
    transports: ['websocket', 'polling'],
    reconnection: false,
    timeout: 120_000,
  })
  const progress: Array<Record<string, unknown>> = []
  const consoleErrors: string[] = []
  const pageErrors: string[] = []

  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const livePage = await context.newPage()
    const dashboardPage = await context.newPage()
    const captureErrors = (page: Page, label: string): void => {
      page.on('console', (message) => {
        if (message.type() === 'error') consoleErrors.push(`${label}: ${message.text()}`)
      })
      page.on('pageerror', (error) => pageErrors.push(`${label}: ${error.message}`))
    }
    captureErrors(livePage, 'live')
    captureErrors(dashboardPage, 'dashboard')
    await livePage.goto(new URL('/live.html', options.baseUrl).href, {
      waitUntil: 'domcontentloaded',
    })
    await livePage.waitForFunction(
      () => document.getElementById('socketStatus')?.dataset.state === 'connected',
      undefined,
      { timeout: 120_000 },
    )
    await dashboardPage.goto(new URL('/dashboard', options.baseUrl).href, {
      waitUntil: 'domcontentloaded',
    })
    await dashboardPage.getByTestId('live-ops-dashboard').waitFor({ state: 'visible' })
    const before = await playbackEvidence(livePage)
    await waitForSocket(trigger, 120_000)

    const terminal = new Promise<Record<string, unknown>>((resolveTerminal, rejectTerminal) => {
      trigger.on('sing:progress', (payload: Record<string, unknown>) => {
        if (payload.task_id === taskId) progress.push(payload)
      })
      trigger.on('sing:complete', (payload: Record<string, unknown>) => {
        if (payload.task_id === taskId) resolveTerminal(payload)
      })
      trigger.on('sing:error', (payload: Record<string, unknown>) => {
        if (payload.task_id === taskId) {
          rejectTerminal(new Error(String(payload.error ?? 'Unknown singing error')))
        }
      })
    })

    const preparedBytes = await readFile(preparedAudio)
    trigger.emit('sing:process', {
      task_id: taskId,
      file_data: preparedBytes.toString('base64'),
      file_name: `${taskId}.wav`,
      lyrics_text: options.lyrics,
      auto_confirm: true,
    })
    process.stdout.write(
      `${JSON.stringify({ task_id: taskId, stage: 'submitted', prepared_bytes: preparedBytes.byteLength })}\n`,
    )
    const complete = await withTimeout(terminal, options.timeoutMs, 'singing pipeline')
    const expectedIdentity = {
      voice_provider: options.expectedProvider,
      voice_model: options.expectedModel,
      voice_revision: options.expectedRevision,
      voice_name: options.expectedVoice,
    }
    const identityMismatches = Object.entries(expectedIdentity).filter(
      ([field, expected]) => complete[field] !== expected,
    )
    if (complete.voice_conversion_applied !== true || identityMismatches.length) {
      throw new Error(
        `Real RVC identity was not proven: ${JSON.stringify({
          voice_conversion_applied: complete.voice_conversion_applied,
          identityMismatches,
        })}`,
      )
    }
    const skippedConversion = progress.find((entry) =>
      String(entry.message ?? '').includes('Voice conversion skipped'),
    )
    if (skippedConversion) {
      throw new Error(`RVC fallback was observed: ${JSON.stringify(skippedConversion)}`)
    }
    const audioUrl = new URL(String(complete.audio_url), options.baseUrl)
    const audioResponse = await fetch(audioUrl)
    const audioBytes = audioResponse.ok ? (await audioResponse.arrayBuffer()).byteLength : 0
    if (!audioResponse.ok || audioBytes <= 44) {
      throw new Error(`Generated audio is not readable: HTTP ${audioResponse.status}`)
    }

    await livePage.waitForFunction(
      ({ expectedTaskId, expectedAudioUrl }) => {
        const status = document.getElementById('audioStatus')
        const audio = document.getElementById('singingAudio') as HTMLAudioElement | null
        return (
          status?.dataset.lastAudioTaskId === expectedTaskId &&
          status?.dataset.lastAudioKind === 'singing' &&
          document.getElementById('singingPlayer') === null &&
          audio?.hidden === true &&
          audio.src === expectedAudioUrl
        )
      },
      { expectedTaskId: taskId, expectedAudioUrl: audioUrl.href },
      { timeout: 30_000 },
    )
    await livePage.waitForFunction(
      () => {
        const audio = document.getElementById('singingAudio') as HTMLAudioElement | null
        return Boolean(audio && !audio.paused && audio.currentTime > 0)
      },
      undefined,
      { timeout: 30_000 },
    )
    await dashboardPage.waitForFunction(
      ({ expectedTaskId, expectedAudioUrl, expectedVoice }) => {
        const result = document.querySelector<HTMLElement>('[data-testid="singing-player-result"]')
        const audio = document.querySelector<HTMLAudioElement>('audio[aria-label="RVC 混音"]')
        const identity = document.querySelector<HTMLElement>(
          '[data-testid="singing-voice-identity"]',
        )
        return (
          result?.dataset.taskId === expectedTaskId &&
          result?.dataset.audioUrl === new URL(expectedAudioUrl).pathname &&
          audio?.src === expectedAudioUrl &&
          identity?.textContent?.includes(expectedVoice)
        )
      },
      {
        expectedTaskId: taskId,
        expectedAudioUrl: audioUrl.href,
        expectedVoice: options.expectedVoice,
      },
      { timeout: 30_000 },
    )
    await dashboardPage.getByRole('button', { name: '播放RVC 混音' }).click()
    await dashboardPage.waitForFunction(
      () => {
        const audio = document.querySelector<HTMLAudioElement>('audio[aria-label="RVC 混音"]')
        return Boolean(audio && !audio.paused && audio.currentTime > 0)
      },
      undefined,
      { timeout: 30_000 },
    )
    const after = await playbackEvidence(livePage)
    const playbackFailures = consoleErrors.filter((message) =>
      /audio] (Chat|Singing) audio playback failed/.test(message),
    )
    if (playbackFailures.length || pageErrors.length) {
      throw new Error(
        `Browser playback errors: ${[...playbackFailures, ...pageErrors].join(' | ')}`,
      )
    }

    const outputPath = resolve(
      options.output ?? join('..', 'artifacts', 'live-singing', taskId, 'evidence.json'),
    )
    const dashboardScreenshot = join(dirname(outputPath), 'dashboard.png')
    const liveScreenshot = join(dirname(outputPath), 'live.png')
    await mkdir(dirname(outputPath), { recursive: true })
    await dashboardPage.screenshot({ path: dashboardScreenshot, fullPage: false })
    await livePage.screenshot({ path: liveScreenshot, fullPage: false })
    const evidence = {
      task_id: taskId,
      base_url: options.baseUrl,
      input: {
        source: options.audioFile,
        duration_seconds: options.durationSeconds,
        prepared_bytes: preparedBytes.byteLength,
      },
      progress,
      complete,
      generated_audio: {
        url: audioUrl.href,
        status: audioResponse.status,
        bytes: audioBytes,
      },
      playback: { before, after },
      live_playback: await livePage.locator('#singingAudio').evaluate((element) => {
        const audio = element as HTMLAudioElement
        return {
          hidden: audio.hidden,
          src: audio.src,
          current_time: audio.currentTime,
          paused: audio.paused,
        }
      }),
      dashboard_player: await dashboardPage
        .getByTestId('singing-player-result')
        .evaluate((element) => {
          const audio = document.querySelector<HTMLAudioElement>('audio[aria-label="RVC 混音"]')
          return {
            visible: true,
            task_id: (element as HTMLElement).dataset.taskId,
            audio_url: (element as HTMLElement).dataset.audioUrl,
            current_time: audio?.currentTime ?? 0,
            paused: audio?.paused ?? true,
            tracks: Array.from(document.querySelectorAll('button[aria-label^="试听"]')).map(
              (track) => track.textContent?.trim() ?? '',
            ),
          }
        }),
      console_errors: consoleErrors,
      page_errors: pageErrors,
      screenshots: { dashboard: dashboardScreenshot, live: liveScreenshot },
      passed: true,
    }
    await writeFile(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, 'utf8')
    const volumes = Array.isArray(complete.volumes) ? complete.volumes : []
    process.stdout.write(
      `${JSON.stringify(
        {
          ...evidence,
          complete: {
            ...complete,
            volumes: {
              samples: volumes.length,
              active_samples: volumes.filter((sample) => Number(sample) > 0).length,
            },
          },
          evidence: outputPath,
        },
        null,
        2,
      )}\n`,
    )
  } finally {
    trigger.disconnect()
    try {
      await browser.close()
    } catch (error) {
      console.warn('[smoke] browser.close failed', error)
    }
    // Always clean the temp dir even if browser.close throws.
    await rm(temporary, { recursive: true, force: true })
  }
}

await main()
