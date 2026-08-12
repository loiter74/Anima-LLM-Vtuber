import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineStage, SongResult } from '@/types/singing'

export const useSingingStore = defineStore('singing', () => {
  const url = ref('')
  const status = ref<PipelineStage>('idle')
  const progress = ref(0)
  const message = ref('')
  const result = ref<SongResult | null>(null)
  const error = ref('')
  const taskId = ref('')

  const isProcessing = computed(() =>
    [
      'downloading',
      'separating',
      'transcribing',
      'waiting_lyrics',
      'converting',
      'mixing',
    ].includes(status.value),
  )

  const isPlaying = ref(false)
  const currentTime = ref(0)
  const currentLyricIndex = ref(-1)
  const playingUrl = ref('')
  const audioElement = ref<HTMLAudioElement | null>(null)

  function setPlaying(url: string, el?: HTMLAudioElement) {
    playingUrl.value = url
    if (el) audioElement.value = el
  }

  function setProgress(stage: PipelineStage, pct: number, msg: string) {
    status.value = stage
    progress.value = pct
    message.value = msg
  }

  function setResult(res: SongResult) {
    result.value = res
    status.value = 'done'
    progress.value = 100
    message.value = ''
    taskId.value = res.task_id || taskId.value
  }

  function setError(err: string) {
    error.value = err
    status.value = 'error'
  }

  function reset() {
    url.value = ''
    status.value = 'idle'
    progress.value = 0
    message.value = ''
    result.value = null
    error.value = ''
    taskId.value = ''
    isPlaying.value = false
    currentTime.value = 0
    currentLyricIndex.value = -1
  }

  return {
    url,
    status,
    progress,
    message,
    result,
    error,
    taskId,
    isProcessing,
    isPlaying,
    currentTime,
    currentLyricIndex,
    playingUrl,
    audioElement,
    setPlaying,
    setProgress,
    setResult,
    setError,
    reset,
  }
})
