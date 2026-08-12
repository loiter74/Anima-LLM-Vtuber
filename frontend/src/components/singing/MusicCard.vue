<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useSingingStore } from '@/stores/singing'
import { useSinging } from '@/composables/useSinging'
import { startLipSync, stopLipSync } from '@/components/live2d/useLipSync'
import { writeSingingPlayback, type SingingPlaybackState } from '@/singing/playback-sync'
import WaveformDisplay from './WaveformDisplay.vue'
import PlaybackControls from './PlaybackControls.vue'
import ProcessTimeline from './ProcessTimeline.vue'

const store = useSingingStore()
const { process, confirmLyrics, cancel } = useSinging()
const inputUrl = ref('')
const inputError = ref('')
const assDraft = ref('')
const waveformRef = ref<InstanceType<typeof WaveformDisplay> | null>(null)
const selectedTrackKey = ref<'mix' | 'vocals' | 'original'>('mix')
const playbackError = ref('')

const tracks = computed(() => {
  const result = store.result
  if (!result) return []
  return [
    { key: 'mix' as const, label: 'RVC 混音', url: result.audio_url },
    { key: 'vocals' as const, label: 'RVC 纯人声', url: result.vocals_url },
    { key: 'original' as const, label: '原始音频', url: result.original_url },
  ].filter((track) => Boolean(track.url))
})
const selectedTrack = computed(
  () => tracks.value.find((track) => track.key === selectedTrackKey.value) ?? tracks.value[0],
)

function startProcess() {
  const url = inputUrl.value.trim()
  if (!/^(https?:\/\/)?((www\.)?bilibili\.com|b23\.tv)\//i.test(url)) {
    inputError.value = '请输入有效的 Bilibili 或 b23.tv 地址'
    return
  }
  inputError.value = ''
  if (store.status === 'error') store.reset()
  process(url)
}

function submitLyrics() {
  const content = assDraft.value.trim()
  if (!content) return
  confirmLyrics(content)
}

function handleTimeupdate(time: number) {
  store.currentTime = time
  if (store.result?.lyrics) {
    const idx = store.result.lyrics.findIndex(
      (l) => time * 1000 >= l.start_ms && time * 1000 <= l.end_ms,
    )
    store.currentLyricIndex = idx
  }
}

function handlePlay() {
  playbackError.value = ''
  store.isPlaying = true
  // Stronger lip sync mode: use pre-computed volumes for RAF-driven mouth
  const vols = store.result?.volumes
  if (vols && vols.length > 0) {
    const el = store.audioElement
    if (el) startLipSync(el, vols)
  }
  syncLivePlayback('playing')
}

function handlePause() {
  store.isPlaying = false
  stopLipSync()
  syncLivePlayback('paused')
}

function syncLivePlayback(
  state: SingingPlaybackState,
  position = store.audioElement?.currentTime ?? 0,
) {
  const result = store.result
  const track = selectedTrack.value
  if (!result || !track) return
  writeSingingPlayback({
    taskId: result.task_id || result.audio_url,
    track: track.key,
    audioUrl: track.url,
    volumes: result.volumes || [],
    durationSeconds: result.duration,
    state,
    positionSeconds: position,
    updatedAtMs: Date.now(),
  })
}

function handleSeek(time: number) {
  handleTimeupdate(time)
  syncLivePlayback(store.isPlaying ? 'playing' : 'paused', time)
}

function handleAudioReady(el: HTMLAudioElement) {
  store.setPlaying(selectedTrack.value?.url || '', el)
  waveformRef.value?.connectAudio(el)
}

function handleAudioEnded() {
  store.isPlaying = false
  stopLipSync()
  syncLivePlayback('completed', store.result?.duration ?? 0)
}

function selectTrack(key: 'mix' | 'vocals' | 'original') {
  if (selectedTrackKey.value === key) return
  stopLipSync()
  store.isPlaying = false
  selectedTrackKey.value = key
  playbackError.value = ''
  syncLivePlayback('paused', 0)
}

function handlePlaybackError() {
  playbackError.value = '浏览器无法播放该音轨，请检查媒体权限后重试。'
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

// session_ids are path-derived (data_singing_uploads_sing-<uuid>-<short>) and
// unreadable when shown verbatim. Surface the creation time as the primary
// label and keep only a short id tail for disambiguation.
function formatRecentTime(item: RecentItem): string {
  if (!item.created_at) return ''
  const d = new Date(item.created_at)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(d)
}

function shortSessionId(sessionId: string): string {
  const parts = sessionId.split(/[-_]/).filter(Boolean)
  const tail = parts.slice(-2).join('-')
  return tail.length > 12 ? tail.slice(-12) : tail
}

function playRecent(item: RecentItem) {
  inputError.value = ''
  playbackError.value = ''
  selectedTrackKey.value = 'mix'
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
    <div class="flex items-start justify-between gap-3">
      <div>
        <div class="text-sm font-medium text-c-text">唱歌播放器</div>
        <p class="mt-1 text-xs text-c-text-muted">制作、试听并核对 RVC 声线</p>
      </div>
      <span
        v-if="store.result?.voice_conversion_applied"
        class="rounded-lg border border-c-success/40 bg-c-success/10 px-2 py-1 text-10px text-c-success"
      >
        RVC 已应用
      </span>
      <span
        v-else
        class="rounded-lg border border-c-border bg-c-panel/45 px-2 py-1 font-mono text-10px uppercase text-c-text-muted"
      >
        {{ store.status }}
      </span>
    </div>

    <!-- URL Input (shown when idle/error) -->
    <div v-if="store.status === 'idle' || store.status === 'error'" class="flex gap-2">
      <input
        v-model="inputUrl"
        placeholder="粘贴 Bilibili 视频地址"
        class="flex-1 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-sm text-c-text placeholder-c-text-dim/50 outline-none focus:border-c-accent/50 transition-all"
        @keyup.enter="startProcess"
      />
      <button
        class="px-4 py-2 rounded-lg bg-c-accent/20 text-c-accent text-sm font-medium hover:bg-c-accent/30 transition-all whitespace-nowrap"
        @click="startProcess"
      >
        开始制作
      </button>
    </div>
    <p v-if="inputError" class="text-xs text-c-error" role="alert">{{ inputError }}</p>

    <!-- Recent works -->
    <div v-if="recentItems.length > 0 && store.status === 'idle'" class="flex flex-col gap-2 mt-2">
      <div class="text-xs text-c-text-dim font-medium">最近作品</div>
      <div
        v-for="item in recentItems"
        :key="item.session_id"
        class="flex items-center gap-2 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs hover:bg-c-bg/60 transition-colors"
      >
        <button
          class="w-7 h-7 flex items-center justify-center rounded-full bg-c-accent/20 text-c-accent hover:bg-c-accent/40 transition-all shrink-0"
          @click="playRecent(item)"
          :title="'载入 ' + item.session_id"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
            <polygon points="5,3 19,12 5,21" />
          </svg>
        </button>
        <div class="flex min-w-0 flex-1 flex-col">
          <span class="truncate text-c-text">{{ formatRecentTime(item) || '未命名作品' }}</span>
          <span class="truncate font-mono text-10px text-c-text-muted">{{
            shortSessionId(item.session_id)
          }}</span>
        </div>
        <a
          :href="item.audio_url"
          class="px-2 py-1 rounded bg-c-accent/20 text-c-accent hover:bg-c-accent/30 transition-colors shrink-0"
          target="_blank"
        >
          音轨
        </a>
        <a
          v-if="item.subtitle_url"
          :href="item.subtitle_url"
          class="px-2 py-1 rounded bg-c-bg/40 text-c-text-dim hover:text-c-text transition-colors shrink-0"
          target="_blank"
        >
          字幕
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
      class="space-y-3 rounded-xl border border-c-warning/30 bg-c-warning/10 px-3 py-3 text-xs text-c-warning"
    >
      <p>歌词已生成，请在 <strong>Aegisub</strong> 中审核时间轴，再粘贴确认后的 ASS 内容。</p>
      <textarea
        v-model="assDraft"
        rows="4"
        class="w-full resize-none rounded-xl border border-c-border bg-c-panel/65 px-3 py-2 font-mono text-10px text-c-text outline-none focus:border-c-border-accent"
        placeholder="粘贴已确认的 ASS 字幕内容"
      />
      <button class="btn-accent" type="button" :disabled="!assDraft.trim()" @click="submitLyrics">
        确认歌词并继续
      </button>
    </div>

    <!-- Cancel button during processing -->
    <button
      v-if="store.isProcessing"
      class="self-start px-3 py-1.5 rounded-lg bg-c-error/10 text-c-error text-xs hover:bg-c-error/20 transition-all"
      @click="cancel"
    >
      取消
    </button>

    <!-- Result: playback controls -->
    <div
      v-if="store.result"
      class="flex flex-col gap-3"
      data-testid="singing-player-result"
      :data-task-id="store.result.task_id || ''"
      :data-audio-url="store.result.audio_url"
    >
      <div
        v-if="store.result.voice_name || store.result.voice_model"
        class="rounded-xl border border-c-border bg-c-panel/35 px-3 py-2"
        data-testid="singing-voice-identity"
      >
        <p class="text-xs text-c-text-secondary">
          当前声线
          <strong class="ml-1 text-c-accent">{{ store.result.voice_name || '未命名声线' }}</strong>
        </p>
        <p class="mt-1 truncate font-mono text-10px text-c-text-muted">
          {{ store.result.voice_provider }} · {{ store.result.voice_model }}
        </p>
      </div>
      <button
        class="self-start flex items-center gap-1 px-2 py-1 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim hover:text-c-accent hover:border-c-accent/30 transition-all"
        @click="store.reset()"
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        >
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
        返回列表
      </button>
      <div class="flex flex-wrap gap-2" role="group" aria-label="试听音轨">
        <button
          v-for="track in tracks"
          :key="track.key"
          class="rounded-lg border px-3 py-1.5 text-xs transition-colors duration-200"
          :class="
            selectedTrack?.key === track.key
              ? 'border-c-border-accent bg-c-accent-soft text-c-accent'
              : 'border-c-border bg-c-panel/35 text-c-text-secondary hover:text-c-text'
          "
          :aria-label="`试听${track.label}`"
          :aria-pressed="selectedTrack?.key === track.key"
          @click="selectTrack(track.key)"
        >
          {{ track.label }}
        </button>
      </div>
      <PlaybackControls
        :key="`${store.result.task_id || store.result.audio_url}:${selectedTrack?.key || 'mix'}`"
        :duration="store.result.duration"
        :audio-url="selectedTrack?.url || store.result.audio_url"
        :label="selectedTrack?.label"
        @play="handlePlay"
        @pause="handlePause"
        @timeupdate="handleTimeupdate"
        @seek="handleSeek"
        @audio-ready="handleAudioReady"
        @ended="handleAudioEnded"
        @error="handlePlaybackError"
      />
      <p v-if="playbackError" class="text-xs text-c-error" role="alert">{{ playbackError }}</p>
      <WaveformDisplay
        ref="waveformRef"
        :is-playing="store.isPlaying"
        :vocals-url="store.result?.vocals_url"
      />

      <!-- Output file links -->
      <div class="flex flex-col gap-2 mt-1">
        <div class="text-xs text-c-text-dim font-medium">输出文件</div>
        <div class="flex flex-wrap gap-2">
          <!-- RVC mixed final audio -->
          <a
            v-if="store.result.audio_url"
            :href="store.result.audio_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-c-accent/10 border border-c-accent/30 text-xs text-c-accent hover:bg-c-accent/20 transition-all"
          >
            RVC 混音
          </a>
          <!-- RVC vocals only (for lip sync) -->
          <a
            v-if="store.result.vocals_url"
            :href="store.result.vocals_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs text-c-text hover:text-c-accent hover:border-c-accent/30 transition-all"
          >
            RVC 纯人声
          </a>
          <!-- Original audio -->
          <a
            v-if="store.result.original_url"
            :href="store.result.original_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim hover:text-c-text hover:border-c-border/60 transition-all"
          >
            原始音频
          </a>
          <!-- TTS voice mix -->
          <a
            v-if="store.result.tts_audio_url"
            :href="store.result.tts_audio_url"
            target="_blank"
            class="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim hover:text-c-accent hover:border-c-accent/30 transition-all"
          >
            TTS 语音
          </a>
        </div>
      </div>

      <!-- Subtitle download -->
      <a
        v-if="store.result.subtitle_url"
        :href="store.result.subtitle_url"
        download
        class="inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-c-bg/40 border border-c-border/30 text-xs text-c-text-dim hover:text-c-accent hover:border-c-accent/30 transition-all"
      >
        下载字幕文件 (.ass)
      </a>
    </div>
  </div>
</template>
