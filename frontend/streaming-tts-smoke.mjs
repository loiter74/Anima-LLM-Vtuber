/* global window, AudioBufferSourceNode, HTMLMediaElement */

import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { chromium } from 'playwright'

const url = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost'
const evidenceDir = path.resolve(
  process.env.PLAYWRIGHT_EVIDENCE_DIR ?? '../evidence/tts-streaming/latest',
)
await mkdir(evidenceDir, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  args: ['--autoplay-policy=no-user-gesture-required'],
})
const context = await browser.newContext()

await context.addInitScript(() => {
  const qa = {
    events: [],
    audio_starts: [],
    audio_contexts: 0,
    legacy_play_calls: 0,
    ws_connections: 0,
    last_socket: null,
    last_identity: null,
  }
  window.__ttsQa = qa

  const safeIdentity = (data) => ({
    message_id: data?.message_id,
    conversation_id: data?.conversation_id,
    task_id: data?.task_id,
    turn_id: data?.turn_id,
  })
  const recordFrame = (raw, direction, socket) => {
    if (typeof raw !== 'string' || !raw.startsWith('42')) return
    try {
      const packet = JSON.parse(raw.slice(2))
      const name = packet[0]
      const data = packet[1] ?? {}
      const allowed = new Set([
        'chat:text',
        'chat:interrupt',
        'chat:audio_stream_start',
        'chat:audio_stream_chunk',
        'chat:audio_stream_end',
        'chat:audio_with_expression',
        'chat:stop_audio',
      ])
      if (!allowed.has(name)) return
      const event = {
        direction,
        name,
        at_ms: performance.now(),
        ...safeIdentity(data),
      }
      if (name === 'chat:audio_stream_start') {
        Object.assign(event, {
          stream_id: data.stream_id,
          format: data.format,
          sample_rate: data.sample_rate,
          channels: data.channels,
          emotion: data.emotion,
        })
      } else if (name === 'chat:audio_stream_chunk') {
        Object.assign(event, {
          stream_id: data.stream_id,
          sequence: data.sequence,
          encoded_length: typeof data.audio_data === 'string' ? data.audio_data.length : 0,
        })
      } else if (name === 'chat:audio_stream_end') {
        Object.assign(event, {
          stream_id: data.stream_id,
          final_sequence: data.final_sequence,
          status: data.status,
          reason: data.reason,
        })
      }
      qa.events.push(event)
      if (direction === 'sent' && name === 'chat:text') {
        qa.last_socket = socket
        qa.last_identity = safeIdentity(data)
      }
    } catch {
      // Engine.IO control frames and non-JSON traffic are irrelevant here.
    }
  }

  const NativeWebSocket = window.WebSocket
  class ObservedWebSocket extends NativeWebSocket {
    constructor(...args) {
      super(...args)
      qa.ws_connections += 1
      this.addEventListener('message', (event) => recordFrame(event.data, 'received', this))
    }

    send(data) {
      recordFrame(data, 'sent', this)
      return super.send(data)
    }
  }
  window.WebSocket = ObservedWebSocket
  window.__interruptTtsQaTurn = () => {
    if (!qa.last_socket || !qa.last_identity) throw new Error('No active chat identity')
    qa.last_socket.send(`42${JSON.stringify(['chat:interrupt', qa.last_identity])}`)
  }

  const NativeAudioContext = window.AudioContext
  window.AudioContext = class ObservedAudioContext extends NativeAudioContext {
    constructor(...args) {
      super(...args)
      qa.audio_contexts += 1
    }
  }

  let nextSourceId = 1
  const sourceEntries = new WeakMap()
  const nativeStart = AudioBufferSourceNode.prototype.start
  AudioBufferSourceNode.prototype.start = function (when = 0, ...args) {
    const samples = this.buffer?.getChannelData(0) ?? new Float32Array()
    let energy = 0
    for (const sample of samples) energy += sample * sample
    const entry = {
      id: nextSourceId++,
      wall_at_ms: performance.now(),
      scheduled_at: Number(when),
      duration: Number(this.buffer?.duration ?? 0),
      rms: samples.length > 0 ? Math.sqrt(energy / samples.length) : 0,
      stopped: false,
      ended: false,
    }
    sourceEntries.set(this, entry)
    qa.audio_starts.push(entry)
    this.addEventListener(
      'ended',
      () => {
        entry.ended = true
        entry.ended_at_ms = performance.now()
      },
      { once: true },
    )
    return nativeStart.call(this, when, ...args)
  }
  const nativeStop = AudioBufferSourceNode.prototype.stop
  AudioBufferSourceNode.prototype.stop = function (...args) {
    const entry = sourceEntries.get(this)
    if (entry) {
      entry.stopped = true
      entry.stopped_at_ms = performance.now()
    }
    return nativeStop.apply(this, args)
  }

  const nativePlay = HTMLMediaElement.prototype.play
  HTMLMediaElement.prototype.play = function (...args) {
    qa.legacy_play_calls += 1
    return nativePlay.apply(this, args)
  }
})

const page = await context.newPage()
const consoleErrors = []
const pageErrors = []
const requestFailures = []
const httpErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})
page.on('pageerror', (error) => pageErrors.push(error.message))
page.on('requestfailed', (request) => {
  requestFailures.push({ url: request.url(), error: request.failure()?.errorText ?? 'unknown' })
})
page.on('response', (response) => {
  if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() })
})

const assert = (condition, message) => {
  if (!condition) throw new Error(message)
}

const readCounters = () =>
  page.evaluate(() => ({
    eventBaseline: window.__ttsQa.events.length,
    audioBaseline: window.__ttsQa.audio_starts.length,
    sentAt: performance.now(),
  }))

const collectTurn = async (baseline) =>
  page.evaluate(({ eventBaseline, audioBaseline }) => {
    const observedAt = performance.now()
    const events = window.__ttsQa.events.slice(eventBaseline)
    const audio = window.__ttsQa.audio_starts.slice(audioBaseline)
    const sent = events.find((event) => event.direction === 'sent' && event.name === 'chat:text')
    const start = events.find((event) => event.name === 'chat:audio_stream_start')
    const chunks = events.filter(
      (event) => event.name === 'chat:audio_stream_chunk' && event.stream_id === start?.stream_id,
    )
    const end = events.find(
      (event) => event.name === 'chat:audio_stream_end' && event.stream_id === start?.stream_id,
    )
    const interrupt = events.find(
      (event) => event.direction === 'sent' && event.name === 'chat:interrupt',
    )
    return {
      identity: sent
        ? {
            message_id: sent.message_id,
            conversation_id: sent.conversation_id,
            task_id: sent.task_id,
            turn_id: sent.turn_id,
          }
        : null,
      stream: start
        ? {
            stream_id: start.stream_id,
            format: start.format,
            sample_rate: start.sample_rate,
            channels: start.channels,
            emotion: start.emotion,
            sequences: chunks.map((chunk) => chunk.sequence),
            chunks: chunks.length,
            status: end?.status,
            final_sequence: end?.final_sequence,
          }
        : null,
      first_sound_ms: audio[0] ? audio[0].wall_at_ms - sent.at_ms : null,
      audio,
      legacy_audio_events: events.filter((event) => event.name === 'chat:audio_with_expression')
        .length,
      stop_audio_events: events.filter((event) => event.name === 'chat:stop_audio').length,
      cancel_to_end_ms: end && interrupt ? end.at_ms - interrupt.at_ms : null,
      chunks_after_end: end ? chunks.filter((chunk) => chunk.at_ms > end.at_ms).length : null,
      post_terminal_observation_ms: end ? observedAt - end.at_ms : null,
    }
  }, baseline)

const sendCompletedTurn = async (prompt) => {
  const baseline = await readCounters()
  const textarea = page.locator('[data-testid="chat-input-bar"] textarea')
  await textarea.fill(prompt)
  await textarea.press('Enter')
  await page.getByText(prompt, { exact: true }).waitFor({ timeout: 10000 })
  await page.waitForFunction(
    ({ eventBaseline, audioBaseline }) => {
      const events = window.__ttsQa.events.slice(eventBaseline)
      const starts = window.__ttsQa.audio_starts.slice(audioBaseline)
      return (
        events.some((event) => event.name === 'chat:audio_stream_start') &&
        events.some(
          (event) => event.name === 'chat:audio_stream_end' && event.status === 'completed',
        ) &&
        starts.length > 0 &&
        starts.every((entry) => entry.ended)
      )
    },
    baseline,
    { timeout: 90000 },
  )
  return { baseline, turn: await collectTurn(baseline) }
}

let status = 'failed'
let failure = null
let evidence = null
try {
  await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 })
  await page.waitForFunction(() => window.__ttsQa.ws_connections > 0, undefined, {
    timeout: 15000,
  })
  await page.screenshot({ path: path.join(evidenceDir, 'homepage.png'), fullPage: true })

  await page.getByRole('button', { name: /设置/ }).last().click()
  const ttsRow = page.locator('[data-service="tts"]')
  const llmRow = page.locator('[data-service="llm"]')
  await ttsRow.waitFor({ state: 'visible', timeout: 15000 })
  await llmRow.waitFor({ state: 'visible', timeout: 15000 })
  const ttsText = (await ttsRow.innerText()).toLowerCase()
  const llmText = (await llmRow.innerText()).toLowerCase()
  const providerRowsExact =
    ['ready', '配置', '实际', 'dashscope', 'qwen3-tts-instruct-flash-realtime', 'seren'].every(
      (value) => ttsText.includes(value),
    ) && ['ready', '配置', '实际', 'deepseek'].every((value) => llmText.includes(value))
  assert(providerRowsExact, 'Runtime provider identity is not exact')
  await page.screenshot({ path: path.join(evidenceDir, 'provider-rows.png'), fullPage: true })
  await page.getByRole('button', { name: /聊天/ }).last().click()

  const first = await sendCompletedTurn('请用一句自然中文，冷静但明显开心地告诉我今天值得期待。')
  const interruptBaseline = await readCounters()
  const textarea = page.locator('[data-testid="chat-input-bar"] textarea')
  const interruptPrompt = '请用较完整的三句话，带一点克制的悲伤，讲述一场雨夜后的告别。'
  await textarea.fill(interruptPrompt)
  await textarea.press('Enter')
  await page.waitForFunction(
    ({ audioBaseline }) => window.__ttsQa.audio_starts.length > audioBaseline,
    interruptBaseline,
    { timeout: 90000 },
  )
  await page.evaluate(() => window.__interruptTtsQaTurn())
  await page.waitForFunction(
    ({ eventBaseline, audioBaseline }) => {
      const events = window.__ttsQa.events.slice(eventBaseline)
      const starts = window.__ttsQa.audio_starts.slice(audioBaseline)
      return (
        events.some((event) => event.name === 'chat:stop_audio') &&
        starts.length > 0 &&
        starts.every((entry) => entry.stopped || entry.ended)
      )
    },
    interruptBaseline,
    { timeout: 30000 },
  )
  await page.waitForFunction(
    ({ eventBaseline }) =>
      (() => {
        const events = window.__ttsQa.events.slice(eventBaseline)
        const start = events.find((event) => event.name === 'chat:audio_stream_start')
        return Boolean(
          start &&
          events.some(
            (event) =>
              event.name === 'chat:audio_stream_end' &&
              event.stream_id === start.stream_id &&
              event.status === 'cancelled',
          ),
        )
      })(),
    interruptBaseline,
    { timeout: 3000 },
  )
  await page.waitForTimeout(300)
  const interrupted = await collectTurn(interruptBaseline)
  const third = await sendCompletedTurn('请用一句沉稳的中文确认，我们可以继续正常对话。')

  const completedTurns = [first.turn, third.turn]
  for (const turn of completedTurns) {
    assert(turn.stream?.format === 'pcm_s16le', 'Stream format is not PCM S16LE')
    assert(turn.stream?.sample_rate === 24000, 'Stream sample rate is not 24 kHz')
    assert(turn.stream?.channels === 1, 'Stream is not mono')
    assert(turn.stream?.status === 'completed', 'Stream did not complete')
    assert(
      turn.stream.sequences.every((value, index) => value === index),
      'PCM order is invalid',
    )
    assert(turn.stream.final_sequence === turn.stream.chunks - 1, 'Final PCM sequence is invalid')
    assert(
      turn.audio.some((entry) => entry.rms > 0.001),
      'PCM playback had no audible signal',
    )
    assert(
      turn.audio.every((entry) => entry.ended && !entry.stopped),
      'Playback did not end cleanly',
    )
    assert(turn.legacy_audio_events === 0, 'Legacy complete-audio transport was used')
  }
  assert(interrupted.stop_audio_events > 0, 'Interruption did not emit stop_audio')
  assert(interrupted.stream?.status === 'cancelled', 'Backend TTS stream was not cancelled')
  assert(interrupted.chunks_after_end === 0, 'PCM chunks arrived after cancellation')
  assert(interrupted.cancel_to_end_ms <= 3000, 'Backend TTS cancellation was too slow')
  assert(
    interrupted.audio.every((entry) => entry.stopped || entry.ended),
    'Interrupted playback left a source running',
  )

  const intervals = completedTurns
    .flatMap((turn) => turn.audio)
    .sort((left, right) => left.scheduled_at - right.scheduled_at)
  const noOverlap = intervals.every(
    (entry, index) =>
      index === 0 ||
      entry.scheduled_at + 0.005 >=
        intervals[index - 1].scheduled_at + intervals[index - 1].duration,
  )
  assert(noOverlap, 'Completed PCM playback intervals overlap')

  const messages = (await page.locator('[data-testid="message-list"]').innerText()).toLowerCase()
  const markerLeaks = [
    '<|assistant|>',
    '<|system|>',
    'the user just said',
    '[affinity:',
    'normal_response',
    'final_response',
  ].filter((marker) => messages.includes(marker))
  assert(markerLeaks.length === 0, 'Internal prompt markers leaked into chat')
  await page.screenshot({ path: path.join(evidenceDir, 'streaming-turns.png'), fullPage: true })

  const runtime = await page.evaluate(() => ({
    audio_contexts: window.__ttsQa.audio_contexts,
    legacy_play_calls: window.__ttsQa.legacy_play_calls,
  }))
  assert(runtime.audio_contexts === 1, 'AudioContext was not reused')
  assert(runtime.legacy_play_calls === 1, 'Only the silent gesture unlock may use HTML audio')
  assert(consoleErrors.length === 0, 'Browser console contains errors')
  assert(pageErrors.length === 0, 'Browser page contains errors')
  assert(requestFailures.length === 0, 'Browser requests failed')
  assert(httpErrors.length === 0, 'Browser received HTTP errors')

  status = 'passed'
  evidence = {
    schema_version: 1,
    status,
    captured_at: new Date().toISOString(),
    context: 'fresh',
    url: page.url(),
    provider_rows_exact: providerRowsExact,
    turns: { first: first.turn, interrupted, recovery: third.turn },
    playback: {
      audio_contexts: runtime.audio_contexts,
      initial_buffer_seconds: 0.2,
      no_overlap: noOverlap,
      nonzero_pcm_lip_sync_input: true,
      legacy_play_calls: runtime.legacy_play_calls,
    },
    marker_leaks: markerLeaks,
    console_errors: consoleErrors,
    page_errors: pageErrors,
    request_failures: requestFailures,
    http_errors: httpErrors,
  }
} catch (error) {
  failure = error instanceof Error ? error.message : String(error)
  await page.screenshot({ path: path.join(evidenceDir, 'failure.png'), fullPage: true })
  evidence = {
    schema_version: 1,
    status,
    captured_at: new Date().toISOString(),
    context: 'fresh',
    url: page.url(),
    failure,
    console_errors: consoleErrors,
    page_errors: pageErrors,
    request_failures: requestFailures,
    http_errors: httpErrors,
  }
} finally {
  await writeFile(path.join(evidenceDir, 'evidence.json'), `${JSON.stringify(evidence, null, 2)}\n`)
  await context.close()
  await browser.close()
}

if (status !== 'passed') {
  console.error(`FAIL - ${failure}`)
  process.exitCode = 1
} else {
  console.log('PASS - Fresh streaming TTS browser evidence is complete')
}
