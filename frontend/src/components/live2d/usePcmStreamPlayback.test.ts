import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const setMouthTarget = vi.hoisted(() => vi.fn())
const startLipSync = vi.hoisted(() => vi.fn())
const stopLipSync = vi.hoisted(() => vi.fn())
const setExpression = vi.hoisted(() => vi.fn())

vi.mock('./useLipSync', () => ({ setMouthTarget, startLipSync, stopLipSync }))
vi.mock('./useLive2DModel', () => ({ setExpression }))

interface StreamStart {
  stream_id: string
  format: 'pcm_s16le'
  sample_rate: number
  channels: number
}

interface StreamChunk {
  stream_id: string
  sequence: number
  audio_data: string
}

interface StreamEnd {
  stream_id: string
  final_sequence: number
  status: 'completed' | 'failed' | 'cancelled'
}

interface PlaybackModule {
  startAudioStream(
    data: StreamStart,
    lifecycle?: {
      onStart?: () => void
      onComplete?: () => void
      onCancel?: () => void
    },
    mouthTarget?: (value: number) => void,
  ): void
  pushAudioStreamChunk(data: StreamChunk): void
  endAudioStream(data: StreamEnd): void
  playAudio(data: { audio_data: string; format: string }): void
  stopAudio(): void
}

class MockAudio {
  static instances: MockAudio[] = []

  currentTime = 0
  onended: (() => void) | null = null
  src = ''
  pause = vi.fn()
  load = vi.fn()
  play = vi.fn(() => Promise.resolve())

  constructor() {
    MockAudio.instances.push(this)
  }

  removeAttribute(name: string): void {
    if (name === 'src') this.src = ''
  }
}

class MockAudioBuffer {
  readonly channelData: Float32Array

  constructor(length: number) {
    this.channelData = new Float32Array(length)
  }

  copyToChannel(source: Float32Array): void {
    this.channelData.set(source)
  }

  getChannelData(): Float32Array {
    return this.channelData
  }
}

class MockBufferSource {
  buffer: MockAudioBuffer | null = null
  onended: (() => void) | null = null
  connect = vi.fn()
  start = vi.fn()
  stop = vi.fn()
}

class MockAudioContext {
  static instances: MockAudioContext[] = []

  currentTime = 1
  destination = {}
  state: AudioContextState = 'running'
  sources: MockBufferSource[] = []
  resume = vi.fn(() => Promise.resolve())

  constructor() {
    MockAudioContext.instances.push(this)
  }

  createBuffer(_channels: number, length: number): MockAudioBuffer {
    return new MockAudioBuffer(length)
  }

  createBufferSource(): MockBufferSource {
    const source = new MockBufferSource()
    this.sources.push(source)
    return source
  }
}

function pcmChunk(value: number, durationMs = 50, sampleRate = 24_000): string {
  const sampleCount = Math.round((sampleRate * durationMs) / 1000)
  const bytes = new Uint8Array(sampleCount * 2)
  const view = new DataView(bytes.buffer)
  for (let index = 0; index < sampleCount; index++) {
    view.setInt16(index * 2, value, true)
  }
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

async function loadPlayback(): Promise<PlaybackModule> {
  return (await import('./useAudioPlayback')) as unknown as PlaybackModule
}

function startEvent(streamId = 'stream-a'): StreamStart {
  return {
    stream_id: streamId,
    format: 'pcm_s16le',
    sample_rate: 24_000,
    channels: 1,
  }
}

describe('progressive PCM playback', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()
    vi.useFakeTimers()
    MockAudio.instances = []
    MockAudioContext.instances = []
    vi.stubGlobal('Audio', MockAudio)
    vi.stubGlobal('AudioContext', MockAudioContext)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:legacy-audio'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('reorders chunks, ignores duplicates, and waits for about 200ms before scheduling', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())

    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 1,
      audio_data: pcmChunk(2_000),
    })
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 0,
      audio_data: pcmChunk(1_000),
    })
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 1,
      audio_data: pcmChunk(9_000),
    })
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 2,
      audio_data: pcmChunk(3_000),
    })

    const context = MockAudioContext.instances[0]
    expect(context.sources).toHaveLength(0)

    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 3,
      audio_data: pcmChunk(4_000),
    })

    expect(context.sources).toHaveLength(4)
    expect(context.sources.map((source) => source.buffer?.channelData[0])).toEqual([
      1_000 / 32_768,
      2_000 / 32_768,
      3_000 / 32_768,
      4_000 / 32_768,
    ])
    const startTimes = context.sources.map((source) => source.start.mock.calls[0][0] as number)
    expect(startTimes[0]).toBeGreaterThanOrEqual(context.currentTime)
    expect(startTimes[1] - startTimes[0]).toBeCloseTo(0.05, 5)
    expect(startTimes[2] - startTimes[1]).toBeCloseTo(0.05, 5)
    expect(startTimes[3] - startTimes[2]).toBeCloseTo(0.05, 5)
  })

  it('flushes a completed short utterance below the initial jitter threshold', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 0,
      audio_data: pcmChunk(1_000),
    })
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 1,
      audio_data: pcmChunk(2_000),
    })

    expect(MockAudioContext.instances[0].sources).toHaveLength(0)
    playback.endAudioStream({
      stream_id: 'stream-a',
      final_sequence: 1,
      status: 'completed',
    })

    expect(MockAudioContext.instances[0].sources).toHaveLength(2)
  })

  it('rejects a completed stream with a missing sequence instead of playing partial audio', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 0,
      audio_data: pcmChunk(1_000),
    })
    playback.pushAudioStreamChunk({
      stream_id: 'stream-a',
      sequence: 2,
      audio_data: pcmChunk(3_000),
    })
    playback.endAudioStream({
      stream_id: 'stream-a',
      final_sequence: 2,
      status: 'completed',
    })

    expect(MockAudioContext.instances[0].sources).toHaveLength(0)
    expect(setMouthTarget).toHaveBeenLastCalledWith(0)
  })

  it('derives non-zero lip-sync targets from received PCM amplitude', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(12_000),
      })
    }

    await vi.runOnlyPendingTimersAsync()

    expect(setMouthTarget.mock.calls.some(([value]) => Number(value) > 0)).toBe(true)
  })

  it('routes PCM lip-sync targets to the active stage', async () => {
    const playback = await loadPlayback()
    const stageMouthTarget = vi.fn()
    playback.startAudioStream(startEvent(), undefined, stageMouthTarget)
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(12_000),
      })
    }

    await vi.runOnlyPendingTimersAsync()

    expect(stageMouthTarget.mock.calls.some(([value]) => Number(value) > 0)).toBe(true)
    expect(setMouthTarget.mock.calls.some(([value]) => Number(value) > 0)).toBe(false)
  })

  it('makes quiet speech visible while keeping silence below the mouth noise gate', async () => {
    const playback = await loadPlayback()
    const stageMouthTarget = vi.fn()
    playback.startAudioStream(startEvent(), undefined, stageMouthTarget)
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(700),
      })
    }

    await vi.runOnlyPendingTimersAsync()

    expect(
      Math.max(...stageMouthTarget.mock.calls.map(([value]) => Number(value))),
    ).toBeGreaterThan(0.2)

    playback.stopAudio()
    stageMouthTarget.mockClear()
    playback.startAudioStream(startEvent('stream-silence'), undefined, stageMouthTarget)
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-silence',
        sequence,
        audio_data: pcmChunk(100),
      })
    }
    await vi.runOnlyPendingTimersAsync()

    expect(stageMouthTarget.mock.calls.every(([value]) => Number(value) === 0)).toBe(true)
  })

  it('stops every scheduled source on interruption and prevents overlap with legacy audio', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(4_000),
      })
    }
    const sources = [...MockAudioContext.instances[0].sources]

    playback.playAudio({ audio_data: btoa('legacy wav'), format: 'wav' })

    expect(sources.every((source) => source.stop.mock.calls.length === 1)).toBe(true)
    expect(MockAudio.instances[0].play).toHaveBeenCalledTimes(1)
    expect(setMouthTarget).toHaveBeenLastCalledWith(0)
  })

  it('terminates buffered playback immediately when the backend ends the stream as failed', async () => {
    const playback = await loadPlayback()
    playback.startAudioStream(startEvent())
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(4_000),
      })
    }
    const sources = [...MockAudioContext.instances[0].sources]

    playback.endAudioStream({
      stream_id: 'stream-a',
      final_sequence: 3,
      status: 'failed',
    })

    expect(sources.every((source) => source.stop.mock.calls.length === 1)).toBe(true)
    expect(setMouthTarget).toHaveBeenLastCalledWith(0)
  })

  it('notifies start at the first scheduled audio frame and completes after drain', async () => {
    const playback = await loadPlayback()
    const lifecycle = {
      onStart: vi.fn(),
      onComplete: vi.fn(),
      onCancel: vi.fn(),
    }
    playback.startAudioStream(startEvent(), lifecycle)
    for (let sequence = 0; sequence < 4; sequence++) {
      playback.pushAudioStreamChunk({
        stream_id: 'stream-a',
        sequence,
        audio_data: pcmChunk(4_000),
      })
    }

    expect(lifecycle.onStart).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(20)
    expect(lifecycle.onStart).toHaveBeenCalledTimes(1)

    playback.endAudioStream({
      stream_id: 'stream-a',
      final_sequence: 3,
      status: 'completed',
    })
    for (const source of MockAudioContext.instances[0].sources) source.onended?.()

    expect(lifecycle.onComplete).toHaveBeenCalledTimes(1)
    expect(lifecycle.onCancel).not.toHaveBeenCalled()
  })
})
