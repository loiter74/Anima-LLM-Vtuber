import { ref, onUnmounted } from 'vue'
import { getSocket } from './useSocket'
import { Events } from '@/constants/socket-events'

export function useVoice() {
  const isRecording = ref(false)
  const volume = ref(0)
  const error = ref<string>('')

  let audioContext: AudioContext | null = null
  let stream: MediaStream | null = null
  let sourceNode: MediaStreamAudioSourceNode | null = null
  let scriptProcessor: ScriptProcessorNode | null = null
  let gainNode: GainNode | null = null
  let resampleBuffer: number[] = []
  let chunkCount = 0

  const TARGET_SAMPLE_RATE = 16000
  const CHUNK_SIZE = 512 // 32ms at 16kHz (Silero VAD minimum is 512 samples)

  async function start(): Promise<void> {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      })

      const track = stream.getAudioTracks()[0]
      const sourceRate = track.getSettings().sampleRate || 48000
      const ratio = sourceRate / TARGET_SAMPLE_RATE

      audioContext = new AudioContext({ sampleRate: sourceRate })
      sourceNode = audioContext.createMediaStreamSource(stream)
      scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1)
      gainNode = audioContext.createGain()
      gainNode.gain.value = 3.0

      scriptProcessor.onaudioprocess = (event) => {
        if (!isRecording.value) return
        const input = event.inputBuffer.getChannelData(0)

        // Resample
        const outputLen = Math.floor(input.length / ratio)
        const resampled = new Float32Array(outputLen)
        for (let i = 0; i < outputLen; i++) {
          const idx = i * ratio
          const lo = Math.floor(idx)
          const hi = Math.min(lo + 1, input.length - 1)
          const frac = idx - lo
          resampled[i] = input[lo] * (1 - frac) + input[hi] * frac
        }

        // Volume
        let sum = 0
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
        volume.value = Math.sqrt(sum / input.length)

        // Buffer and send chunks directly via socket
        resampleBuffer.push(...resampled)
        const socket = getSocket()
        while (resampleBuffer.length >= CHUNK_SIZE) {
          const chunk = resampleBuffer.splice(0, CHUNK_SIZE)
          chunkCount++
          if (socket?.connected) {
            socket.emit(Events.CHAT.AUDIO, { audio: chunk })
          }
        }
      }

      sourceNode.connect(gainNode)
      gainNode.connect(scriptProcessor)
      scriptProcessor.connect(audioContext.destination)

      isRecording.value = true
    } catch (err: any) {
      error.value = err.message
      isRecording.value = false
    }
  }

  async function stop(): Promise<void> {
    isRecording.value = false
    volume.value = 0

    gainNode?.disconnect()
    scriptProcessor?.disconnect()
    sourceNode?.disconnect()
    audioContext?.close()
    stream?.getTracks().forEach((t) => t.stop())

    audioContext = null
    stream = null
    sourceNode = null
    scriptProcessor = null
    gainNode = null
    resampleBuffer = []

    // Signal end of audio input
    const socket = getSocket()
    if (socket?.connected) {
      socket.emit(Events.CHAT.AUDIO_END, {})
    }
  }

  function toggle(): void {
    isRecording.value ? stop() : start()
  }

  onUnmounted(() => {
    if (isRecording.value) stop()
  })

  return { isRecording, volume, error, start, stop, toggle }
}
