<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { setMouthTarget } from '@/components/live2d/useLipSync'

const props = defineProps<{
  isPlaying: boolean
  vocalsUrl?: string
}>()

defineExpose({ connectAudio, syncVocalsTime })

const canvasRef = ref<HTMLCanvasElement | null>(null)
let analyser: AnalyserNode | null = null
let source: MediaElementAudioSourceNode | null = null
let audioCtx: AudioContext | null = null
let rafId: number | null = null
let vocalsAudio: HTMLAudioElement | null = null
let vocalsSource: MediaElementAudioSourceNode | null = null
let vocalsAnalyser: AnalyserNode | null = null

function connectAudio(audioEl: HTMLAudioElement) {
  if (!audioCtx) {
    audioCtx = new AudioContext()
  }
  try {
    source = audioCtx.createMediaElementSource(audioEl)
    analyser = audioCtx.createAnalyser()
    analyser.fftSize = 256
    source.connect(analyser)
    // createMediaElementSource reroutes the element's output into the Web Audio
    // graph, so we must reach the destination or the main mix is silent.
    analyser.connect(audioCtx.destination)
  } catch {
    /* already connected */
  }
}

function loadVocalsForLipSync(url: string) {
  if (!url) return
  if (!audioCtx) audioCtx = new AudioContext()
  try {
    vocalsAudio = new Audio(url)
    vocalsAudio.crossOrigin = 'anonymous'
    vocalsAudio.preload = 'auto'
    vocalsSource = audioCtx.createMediaElementSource(vocalsAudio)
    vocalsAnalyser = audioCtx.createAnalyser()
    vocalsAnalyser.fftSize = 256
    vocalsSource.connect(vocalsAnalyser)
    // Don't connect to destination — silent playback for lip sync only
  } catch {
    /* ignore */
  }
}

function syncVocalsTime(time: number) {
  if (vocalsAudio) {
    vocalsAudio.currentTime = time
  }
}

function getMouthValue(): number {
  const a = vocalsAnalyser
  if (!a) return 0
  const data = new Uint8Array(a.frequencyBinCount)
  a.getByteTimeDomainData(data)
  let sum = 0
  for (let i = 0; i < data.length; i++) sum += Math.abs(data[i] - 128)
  return Math.min(1, sum / data.length / 30)
}

function startDrawing() {
  // Start lip sync even if canvas/analyser not ready (pure vocals driver)
  const doLipSync = !!(vocalsAnalyser || analyser)
  if (!canvasRef.value && !doLipSync) return

  // Only draw waveform if canvas and analyser are available
  const canvas = canvasRef.value
  let ctx: CanvasRenderingContext2D | null = null
  if (canvas) ctx = canvas.getContext('2d')

  const bufferLength = analyser?.frequencyBinCount ?? 128
  const dataArray = analyser ? new Uint8Array(bufferLength) : new Uint8Array(0)

  const draw = () => {
    // Lip sync from vocals (priority) or main analyser
    setMouthTarget(getMouthValue())

    if (analyser && ctx) {
      analyser.getByteTimeDomainData(dataArray)
      ctx.fillStyle = 'rgba(26, 16, 40, 0.3)'
      ctx.fillRect(0, 0, canvas!.width, canvas!.height)
      ctx.lineWidth = 2
      ctx.strokeStyle = '#e879a8'
      ctx.beginPath()
      const sliceWidth = canvas!.width / bufferLength
      let x = 0
      for (let i = 0; i < bufferLength; i++) {
        const v = dataArray[i] / 128.0
        const y = (v * canvas!.height) / 2
        if (i === 0) {
          ctx.moveTo(x, y)
        } else {
          ctx.lineTo(x, y)
        }
        x += sliceWidth
      }
      ctx.lineTo(canvas!.width, canvas!.height / 2)
      ctx.stroke()
    }

    rafId = requestAnimationFrame(draw)
  }
  draw()
}

function stopDrawing() {
  if (rafId) {
    cancelAnimationFrame(rafId)
    rafId = null
  }
  setMouthTarget(0)
}

watch(
  () => props.vocalsUrl,
  (url) => {
    if (url) {
      if (!audioCtx) audioCtx = new AudioContext()
      loadVocalsForLipSync(url)
    }
  },
)

watch(
  () => props.isPlaying,
  async (playing) => {
    if (playing) {
      if (audioCtx?.state === 'suspended') await audioCtx.resume()
      startDrawing()
      vocalsAudio?.play().catch(() => {})
    } else {
      stopDrawing()
      vocalsAudio?.pause()
    }
  },
)

onUnmounted(() => {
  stopDrawing()
  vocalsAudio?.pause()
  vocalsAudio = null
  source?.disconnect()
  vocalsSource?.disconnect()
  audioCtx?.close()
})
</script>

<template>
  <canvas ref="canvasRef" class="w-full h-16 rounded-lg" width="340" height="64" />
</template>
