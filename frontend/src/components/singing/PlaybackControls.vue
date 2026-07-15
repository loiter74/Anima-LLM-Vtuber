<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  duration: number
  audioUrl: string
}>()

const emit = defineEmits<{
  play: []
  pause: []
  timeupdate: [time: number]
  audioReady: [el: HTMLAudioElement]
  ended: []
}>()

const audioRef = ref<HTMLAudioElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const isDragging = ref(false)

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function togglePlay() {
  const audio = audioRef.value
  if (!audio) return
  if (isPlaying.value) {
    audio.pause()
    isPlaying.value = false
    emit('pause')
  } else {
    audio.play()
    isPlaying.value = true
    emit('play')
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
    emit('audioReady', audioRef.value)
  }
}

function onEnded() {
  isPlaying.value = false
  currentTime.value = 0
  emit('ended')
}

function seekFromEvent(e: MouseEvent) {
  const bar = (e.currentTarget || e.target) as HTMLElement
  const rect = bar.getBoundingClientRect()
  const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
  if (audioRef.value) {
    audioRef.value.currentTime = ratio * props.duration
    currentTime.value = ratio * props.duration
  }
}

function onBarMouseDown(e: MouseEvent) {
  isDragging.value = true
  seekFromEvent(e)
  document.addEventListener('mousemove', onBarMouseMove)
  document.addEventListener('mouseup', onBarMouseUp)
}

function onBarMouseMove(e: MouseEvent) {
  if (isDragging.value) seekFromEvent(e)
}

function onBarMouseUp() {
  isDragging.value = false
  document.removeEventListener('mousemove', onBarMouseMove)
  document.removeEventListener('mouseup', onBarMouseUp)
}

const progressPercent = computed(() =>
  props.duration > 0 ? (currentTime.value / props.duration) * 100 : 0,
)
</script>

<template>
  <div class="flex flex-col gap-2">
    <audio
      ref="audioRef"
      :src="audioUrl"
      @timeupdate="onTimeUpdate"
      @ended="onEnded"
      @loadedmetadata="onLoadedMetadata"
    />

    <!-- Progress bar -->
    <div
      class="relative h-2 bg-c-bg/40 rounded-full cursor-pointer overflow-hidden"
      @mousedown="onBarMouseDown"
    >
      <div
        class="absolute inset-y-0 left-0 bg-c-accent rounded-full transition-all"
        :style="{ width: `${progressPercent}%` }"
      />
      \n
    </div>

    <!-- Controls -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-3">
        <button
          class="w-10 h-10 flex items-center justify-center rounded-full bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-all"
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
          {{ formatTime(currentTime) }} / {{ formatTime(duration) }}
        </span>
      </div>
    </div>
  </div>
</template>
