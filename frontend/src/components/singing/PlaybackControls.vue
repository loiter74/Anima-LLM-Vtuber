<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'

const props = defineProps<{
  duration: number
  audioUrl: string
  label?: string
}>()

const emit = defineEmits<{
  play: []
  pause: []
  timeupdate: [time: number]
  seek: [time: number]
  audioReady: [el: HTMLAudioElement]
  ended: []
  error: []
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const progressBarRef = ref<HTMLElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const isDragging = ref(false)
const mediaDuration = ref(0)
const effectiveDuration = computed(() =>
  props.duration > 0 ? props.duration : mediaDuration.value,
)

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

async function togglePlay() {
  const audio = audioRef.value
  if (!audio) return
  if (isPlaying.value) {
    audio.pause()
    isPlaying.value = false
    emit('pause')
  } else {
    try {
      await audio.play()
      isPlaying.value = true
      emit('play')
    } catch {
      isPlaying.value = false
      emit('error')
    }
  }
}

function onTimeUpdate() {
  if (audioRef.value && !isDragging.value) {
    currentTime.value = audioRef.value.currentTime
    emit('timeupdate', currentTime.value)
  }
}

function onLoadedMetadata() {
  if (audioRef.value) {
    if (Number.isFinite(audioRef.value.duration)) mediaDuration.value = audioRef.value.duration
    emit('audioReady', audioRef.value)
  }
}

function onEnded() {
  isPlaying.value = false
  currentTime.value = 0
  emit('ended')
}

function seekTo(clientX: number) {
  const bar = progressBarRef.value
  const audio = audioRef.value
  if (!bar || !audio) return
  const rect = bar.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  const t = ratio * effectiveDuration.value
  audio.currentTime = t
  currentTime.value = t
}

function onBarMouseDown(e: MouseEvent) {
  isDragging.value = true
  seekTo(e.clientX)
  document.addEventListener('mousemove', onBarMouseMove)
  document.addEventListener('mouseup', onBarMouseUp)
}

function onBarMouseMove(e: MouseEvent) {
  if (isDragging.value) seekTo(e.clientX)
}

function onBarMouseUp() {
  isDragging.value = false
  emit('seek', currentTime.value)
  document.removeEventListener('mousemove', onBarMouseMove)
  document.removeEventListener('mouseup', onBarMouseUp)
}

// The drag listeners live on `document`; a track switch rebuilds this component
// mid-drag via the parent :key, so remove them defensively on unmount too.
onUnmounted(() => {
  document.removeEventListener('mousemove', onBarMouseMove)
  document.removeEventListener('mouseup', onBarMouseUp)
})

const progressPercent = computed(() =>
  effectiveDuration.value > 0 ? (currentTime.value / effectiveDuration.value) * 100 : 0,
)
</script>

<template>
  <div class="flex flex-col gap-2">
    <audio
      ref="audioRef"
      :src="audioUrl"
      :aria-label="label || '唱歌音频'"
      @timeupdate="onTimeUpdate"
      @ended="onEnded"
      @loadedmetadata="onLoadedMetadata"
    />

    <!-- Progress bar -->
    <div
      ref="progressBarRef"
      class="relative h-2 bg-c-bg/40 rounded-full cursor-pointer overflow-hidden"
      @mousedown="onBarMouseDown"
    >
      <div
        class="absolute inset-y-0 left-0 bg-c-accent rounded-full transition-all"
        :style="{ width: `${progressPercent}%` }"
      />
    </div>

    <!-- Controls -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          class="w-10 h-10 flex items-center justify-center rounded-full bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-all"
          :aria-label="`${isPlaying ? '暂停' : '播放'}${label || '唱歌音频'}`"
          @click="togglePlay"
        >
          <svg v-if="isPlaying" width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <rect x="6" y="4" width="4" height="16" />
            <rect x="14" y="4" width="4" height="16" />
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,3 19,12 5,21" />
          </svg>
        </button>

        <span class="text-xs text-c-text-dim font-mono">
          {{ formatTime(currentTime) }} / {{ formatTime(effectiveDuration) }}
        </span>
      </div>
    </div>
  </div>
</template>
