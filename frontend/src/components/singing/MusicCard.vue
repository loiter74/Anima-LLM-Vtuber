<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useSingingStore } from '@/stores/singing'
import { useSinging } from '@/composables/useSinging'
import { startLipSync, stopLipSync } from '@/components/live2d/useLipSync'
import WaveformDisplay from './WaveformDisplay.vue'
import PlaybackControls from './PlaybackControls.vue'
import ProcessTimeline from './ProcessTimeline.vue'

const store = useSingingStore()
const { process, cancel } = useSinging()
const inputUrl = ref('')
const waveformRef = ref<InstanceType<typeof WaveformDisplay> | null>(null)

function startProcess() {
  if (!inputUrl.value.trim()) return
  process(inputUrl.value.trim())
}

function handleTimeupdate(time: number) {
  store.currentTime = time
  if (store.result?.lyrics) {
    const idx = store.result.lyrics.findIndex(
      l => time * 1000 >= l.start_ms && time * 1000 <= l.end_ms
    )
    store.currentLyricIndex = idx
  }
}

function handlePlay() {
  store.isPlaying = true
  // Stronger lip sync mode: use pre-computed volumes for RAF-driven mouth
  const vols = store.result?.volumes
  if (vols && vols.length > 0) {
    const el = store.audioElement
    if (el) startLipSync(el, vols)
  }
}

function handlePause() {
  store.isPlaying = false
  stopLipSync()
}

function handleAudioReady(el: HTMLAudioElement) {
  store.setPlaying(store.result?.audio_url || '', el)
  waveformRef.value?.connectAudio(el)
}

function handleAudioEnded() {
  store.isPlaying = false
  stopLipSync()
}

interface RecentItem {
  session_id: string
  audio_url: string
  vocals_url: string
  original_url: string
  subtitle_url: string
  tts_audio_url: string
  created_at: string
  duration_sec: number
}

const recentItems = ref<RecentItem[]>([])
const loadingRecent = ref(false)

async function loadRecent() {
  loadingRecent.value = true
  try {
    const res = await fetch('/api/singing/recent')
    if (res.ok) {
      recentItems.value = await res.json()
    }
  } catch {
    // silently fail
  } finally {
    loadingRecent.value = false
  }
}

onMounted(loadRecent)

function playRecent(item: RecentItem) {
  store.setResult({
    audio_url: item.audio_url,
    subtitle_url: item.subtitle_url || '',
    tts_audio_url: item.tts_audio_url || '',
    vocals_url: item.vocals_url || '',
    original_url: item.original_url || '',
    video_title: item.session_id,
    duration: item.duration_sec,
    lyrics: [],
  })
}
</script>

<template>
  <div class="flex flex-col h-full p-4 gap-4 overflow-y-auto">
    <div class="text-sm font-medium text-c-text">🎵 音乐制作</div>

    <!-- URL Input (shown when idle/error) -->
    <div v-if="store.status === 'idle' || store.status === 'error'" class="flex gap-2">
      <input
        v-model="inputUrl"
        placeholder="📎 贴上 B站 视频链接..."
        class="flex-1 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30
               text-sm text-c-text placeholder-c-text-dim/50 outline-none
               focus:border-c-accent/50 transition-all"
        @keyup.enter="startProcess"
      />
      <button
        class="px-4 py-2 rounded-lg bg-c-accent/20 text-c-accent text-sm
               font-medium hover:bg-c-accent/30 transition-all whitespace-nowrap"
        @click="startProcess"
      >
        开始制作
      </button>
    </div>

    <!-- Recent works -->
    <div v-if="recentItems.length > 0 && store.status === 'idle'" class="flex flex-col gap-2 mt-2">
      <div class="text-xs text-c-text-dim font-medium">Recent Works</div>
      <div
        v-for="item in recentItems"
        :key="item.session_id"
        class="flex items-center gap-2 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs hover:bg-c-bg/60 transition-colors"
      >
        <button
          class="w-7 h-7 flex items-center justify-center rounded-full
                 bg-c-accent/20 text-c-accent hover:bg-c-accent/40 transition-all shrink-0"
          @click="playRecent(item)"
          :title="'Play ' + item.session_id"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,3 19,12 5,21" />
          </svg>
        </button>
        <span class="flex-1 text-c-text truncate">{{ item.session_id }}</span>
        <a
          :href="item.audio_url"
          class="px-2 py-1 rounded bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-colors shrink-0"
          target="_blank"
        >
          DL
        </a>
        <a
          v-if="item.subtitle_url"
          :href="item.subtitle_url"
          class="px-2 py-1 rounded bg-c-bg/40 text-c-text-dim hover:text-c-text transition-colors shrink-0"
          target="_blank"
        >
          Sub
        </a>
      </div>
    </div>

    <!-- Error display -->
    <div
      v-if="store.error"
      class="px-3 py-2 rounded-lg bg-c-error/10 border border-c-error/30 text-xs text-c-error"
    >
      {{ store.error }}
    </div>

    <!-- Processing timeline -->
    <ProcessTimeline
      v-if="store.isProcessing || store.status === 'waiting_lyrics'"
      :current-stage="store.status"
      :progress="store.progress"
      :compact="true"
    />

    <!-- Lyrics confirmation hint -->
    <div
      v-if="store.status === 'waiting_lyrics'"
      class="px-3 py-2 rounded-lg bg-c-gold/10 border border-c-gold/30 text-xs"
      style="color: #f0c060;"
    >
      歌词已生成，请在 <strong>Aegisub</strong> 中审核时间轴后确认。
    </div>

    <!-- Cancel button during processing -->
    <button
      v-if="store.isProcessing"
      class="self-start px-3 py-1.5 rounded-lg bg-c-error/10 text-c-error
             text-xs hover:bg-c-error/20 transition-all"
      @click="cancel"
    >
      取消
    </button>

    <!-- Result: playback controls -->
    <div v-if="store.result" class="flex flex-col gap-3">
      <button
        class="self-start flex items-center gap-1 px-2 py-1 rounded-lg
               bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim
               hover:text-c-accent hover:border-c-accent/30 transition-all"
        @click="store.reset()"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
        返回列表
      </button>
      <PlaybackControls
        :duration="store.result.duration"
        :audio-url="store.result.audio_url"
        @play="handlePlay"
        @pause="handlePause"
        @timeupdate="handleTimeupdate"
        @audio-ready="handleAudioReady"
        @ended="handleAudioEnded"
      />
      <WaveformDisplay ref="waveformRef" :is-playing="store.isPlaying" :vocals-url="store.result?.vocals_url" />

      <!-- Output file links -->
      <div class="flex flex-col gap-2 mt-1">
        <div class="text-xs text-c-text-dim font-medium">📂 输出文件</div>
        <div class="flex flex-wrap gap-2">
          <!-- RVC mixed final audio -->
          <a
            v-if="store.result.audio_url"
            :href="store.result.audio_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg
                   bg-c-accent/10 border border-c-accent/30 text-xs text-c-accent
                   hover:bg-c-accent/20 transition-all"
          >
            🎵 RVC混音 (播放)
          </a>
          <!-- RVC vocals only (for lip sync) -->
          <a
            v-if="store.result.vocals_url"
            :href="store.result.vocals_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg
                   bg-c-bg/40 border border-c-border/30 text-xs text-c-text
                   hover:text-c-accent hover:border-c-accent/30 transition-all"
          >
            🎤 纯人声 (口型)
          </a>
          <!-- Original audio -->
          <a
            v-if="store.result.original_url"
            :href="store.result.original_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg
                   bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim
                   hover:text-c-text hover:border-c-border/60 transition-all"
          >
            📻 原始音频
          </a>
          <!-- TTS voice mix -->
          <a
            v-if="store.result.tts_audio_url"
            :href="store.result.tts_audio_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg
                   bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim
                   hover:text-c-accent hover:border-c-accent/30 transition-all"
          >
            🤖 TTS语音
          </a>
        </div>
      </div>

      <!-- Subtitle download -->
      <a
        v-if="store.result.subtitle_url"
        :href="store.result.subtitle_url"
        download
        class="inline-flex items-center gap-2 px-3 py-2 rounded-lg
               bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim
               hover:text-c-accent hover:border-c-accent/30 transition-all"
      >
        📝 下载字幕文件 (.ass)
      </a>
    </div>
  </div>
</template>
