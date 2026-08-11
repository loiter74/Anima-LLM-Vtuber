import type {
  AudioStreamChunkEvent,
  AudioStreamEndEvent,
  AudioStreamStartEvent,
} from '@/types/socket-events'
import { setMouthTarget, type MouthTarget } from './useLipSync'
import type { AudioPlaybackLifecycle } from './useAudioPlayback'

const INITIAL_BUFFER_SECONDS = 0.2
const PLAYBACK_LEAD_SECONDS = 0.02
const LIP_SYNC_FRAME_SECONDS = 0.02

interface DecodedChunk {
  sequence: number
  samples: Float32Array
}

interface ActivePcmStream {
  id: string
  context: AudioContext
  sampleRate: number
  nextSequence: number
  pending: Map<number, DecodedChunk>
  ready: DecodedChunk[]
  bufferedFrames: number
  started: boolean
  ended: boolean
  nextStartAt: number
  sources: Set<AudioBufferSourceNode>
  lipSyncTimers: Set<ReturnType<typeof setTimeout>>
  lifecycle: AudioPlaybackLifecycle | null
  startNotified: boolean
  setMouthTarget: MouthTarget
}

let pcmAudioContext: AudioContext | null = null
let activePcmStream: ActivePcmStream | null = null

function getPcmAudioContext(): AudioContext | null {
  if (pcmAudioContext) return pcmAudioContext
  if (typeof AudioContext === 'undefined') return null
  pcmAudioContext = new AudioContext({ sampleRate: 24_000 })
  return pcmAudioContext
}

function resumeContext(context: AudioContext): void {
  if (context.state !== 'suspended') return
  context.resume().catch((error: unknown) => {
    console.warn('[audio] Unable to resume streaming audio context', error)
  })
}

function decodePcm16Le(audioData: string): Float32Array | null {
  try {
    const binary = atob(audioData)
    if (!binary.length || binary.length % 2 !== 0) return null
    const bytes = new Uint8Array(binary.length)
    for (let index = 0; index < binary.length; index++) {
      bytes[index] = binary.charCodeAt(index)
    }
    const view = new DataView(bytes.buffer)
    const samples = new Float32Array(binary.length / 2)
    for (let index = 0; index < samples.length; index++) {
      samples[index] = view.getInt16(index * 2, true) / 32_768
    }
    return samples
  } catch {
    return null
  }
}

function scheduleMouthTargets(
  stream: ActivePcmStream,
  samples: Float32Array,
  startAt: number,
): void {
  const frameLength = Math.max(1, Math.round(stream.sampleRate * LIP_SYNC_FRAME_SECONDS))
  for (let offset = 0; offset < samples.length; offset += frameLength) {
    const end = Math.min(samples.length, offset + frameLength)
    let squareSum = 0
    for (let index = offset; index < end; index++) {
      squareSum += samples[index] * samples[index]
    }
    const rms = Math.sqrt(squareSum / (end - offset))
    const mouthTarget = Math.min(1, rms * 3)
    const delayMs = Math.max(
      0,
      (startAt - stream.context.currentTime + offset / stream.sampleRate) * 1000,
    )
    const timer = setTimeout(() => {
      stream.lipSyncTimers.delete(timer)
      if (activePcmStream === stream) stream.setMouthTarget(mouthTarget)
    }, delayMs)
    stream.lipSyncTimers.add(timer)
  }
}

function scheduleChunk(stream: ActivePcmStream, chunk: DecodedChunk): void {
  const buffer = stream.context.createBuffer(1, chunk.samples.length, stream.sampleRate)
  buffer.getChannelData(0).set(chunk.samples)
  const source = stream.context.createBufferSource()
  source.buffer = buffer
  source.connect(stream.context.destination)
  const startAt = stream.nextStartAt
  stream.nextStartAt += chunk.samples.length / stream.sampleRate
  stream.sources.add(source)
  source.onended = () => {
    stream.sources.delete(source)
    if (stream.ended && stream.sources.size === 0 && activePcmStream === stream) {
      stream.setMouthTarget(0)
      activePcmStream = null
      stream.lifecycle?.onComplete?.()
    }
  }
  scheduleMouthTargets(stream, chunk.samples, startAt)
  source.start(startAt)
}

function flushReadyChunks(stream: ActivePcmStream): void {
  if (!stream.started) {
    stream.started = true
    stream.nextStartAt = Math.max(
      stream.nextStartAt,
      stream.context.currentTime + PLAYBACK_LEAD_SECONDS,
    )
    const startDelayMs = Math.max(0, (stream.nextStartAt - stream.context.currentTime) * 1000)
    const startTimer = setTimeout(() => {
      stream.lipSyncTimers.delete(startTimer)
      if (activePcmStream === stream && !stream.startNotified) {
        stream.startNotified = true
        stream.lifecycle?.onStart?.()
      }
    }, startDelayMs)
    stream.lipSyncTimers.add(startTimer)
  }
  for (const chunk of stream.ready.splice(0)) scheduleChunk(stream, chunk)
  stream.bufferedFrames = 0
}

function drainSequentialChunks(stream: ActivePcmStream): void {
  while (stream.pending.has(stream.nextSequence)) {
    const chunk = stream.pending.get(stream.nextSequence)
    stream.pending.delete(stream.nextSequence)
    if (!chunk) break
    stream.ready.push(chunk)
    stream.bufferedFrames += chunk.samples.length
    stream.nextSequence += 1
  }
  if (stream.started) {
    flushReadyChunks(stream)
  } else if (stream.bufferedFrames / stream.sampleRate >= INITIAL_BUFFER_SECONDS) {
    flushReadyChunks(stream)
  }
}

export function unlockPcmAudioPlayback(): void {
  const context = getPcmAudioContext()
  if (context) resumeContext(context)
}

export function startPcmAudioStream(
  data: AudioStreamStartEvent,
  lifecycle?: AudioPlaybackLifecycle,
  mouthTarget: MouthTarget = setMouthTarget,
): void {
  stopPcmAudioStream()
  if (data.format !== 'pcm_s16le' || data.sample_rate !== 24_000 || data.channels !== 1) {
    console.warn('[audio] Rejected unsupported streaming PCM format')
    return
  }
  const context = getPcmAudioContext()
  if (!context) return
  resumeContext(context)
  activePcmStream = {
    id: data.stream_id,
    context,
    sampleRate: data.sample_rate,
    nextSequence: 0,
    pending: new Map(),
    ready: [],
    bufferedFrames: 0,
    started: false,
    ended: false,
    nextStartAt: 0,
    sources: new Set(),
    lipSyncTimers: new Set(),
    lifecycle: lifecycle ?? null,
    startNotified: false,
    setMouthTarget: mouthTarget,
  }
}

export function pushPcmAudioStreamChunk(data: AudioStreamChunkEvent): void {
  const stream = activePcmStream
  if (!stream || data.stream_id !== stream.id || !Number.isInteger(data.sequence)) return
  if (data.sequence < stream.nextSequence || stream.pending.has(data.sequence)) return
  const samples = decodePcm16Le(data.audio_data)
  if (!samples) {
    stopPcmAudioStream()
    return
  }
  stream.pending.set(data.sequence, { sequence: data.sequence, samples })
  drainSequentialChunks(stream)
}

export function endPcmAudioStream(data: AudioStreamEndEvent): void {
  const stream = activePcmStream
  if (!stream || data.stream_id !== stream.id) return
  if (data.status !== 'completed') {
    stopPcmAudioStream()
    return
  }
  const lastReceivedSequence = stream.nextSequence - 1
  if (data.final_sequence !== lastReceivedSequence || stream.pending.size > 0) {
    stopPcmAudioStream()
    return
  }
  if (!stream.started && stream.ready.length > 0) flushReadyChunks(stream)
  stream.ended = true
  if (stream.sources.size === 0) {
    stream.setMouthTarget(0)
    activePcmStream = null
    stream.lifecycle?.onComplete?.()
    return
  }
  const delayMs = Math.max(0, (stream.nextStartAt - stream.context.currentTime) * 1000)
  const timer = setTimeout(() => {
    stream.lipSyncTimers.delete(timer)
    if (activePcmStream === stream) {
      stream.setMouthTarget(0)
      activePcmStream = null
      stream.lifecycle?.onComplete?.()
    }
  }, delayMs)
  stream.lipSyncTimers.add(timer)
}

export function stopPcmAudioStream(): void {
  const stream = activePcmStream
  activePcmStream = null
  if (stream) {
    for (const timer of stream.lipSyncTimers) clearTimeout(timer)
    stream.lipSyncTimers.clear()
    for (const source of stream.sources) {
      source.onended = null
      try {
        source.stop()
      } catch {
        // A source that already ended is harmless during interruption cleanup.
      }
    }
    stream.sources.clear()
    stream.lifecycle?.onCancel?.()
  }
  const resetMouthTarget = stream?.setMouthTarget ?? setMouthTarget
  resetMouthTarget(0)
}
