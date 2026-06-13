<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useSingingStore } from '@/stores/singing'
import { useSinging } from '@/composables/useSinging'
import PlaybackControls from '@/components/singing/PlaybackControls.vue'
import ProcessTimeline from '@/components/singing/ProcessTimeline.vue'
import WaveformDisplay from '@/components/singing/WaveformDisplay.vue'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'

const store = useSingingStore()
const { process, cancel } = useSinging()

const inputUrl = ref('')
const waveformRef = ref<InstanceType<typeof WaveformDisplay> | null>(null)
const isMixedPlaying = ref(false)

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

const isIdle = computed(() => store.status === 'idle' || store.status === 'error')
const isProcessing = computed(() => store.isProcessing || store.status === 'waiting_lyrics')
const hasResult = computed(() => store.result !== null)

function startProcess() {
  if (!inputUrl.value.trim()) return
  process(inputUrl.value.trim())
}

function handleTimeupdate(time: number) {
  store.currentTime = time

  // Sync vocals audio for lip sync
  waveformRef.value?.syncVocalsTime(time)

  if (store.result?.lyrics?.length) {
    const idx = store.result.lyrics.findIndex(
      l => time * 1000 >= l.start_ms && time * 1000 <= l.end_ms
    )
    if (idx !== store.currentLyricIndex) {
      store.currentLyricIndex = idx

      // Emit subtitle sync event for SubtitleOverlay
      const socket = getSocket()
      if (socket?.connected) {
        const line = store.result.lyrics[idx]
        if (line) {
          socket.emit(Events.SING.SUBTITLE_SYNC, {
            index: idx,
            text: line.text,
            translation: line.translation || '',
            start_ms: line.start_ms,
            end_ms: line.end_ms,
          })
        }
      }
    }
  }
}

function handleMixedAudioReady(el: HTMLAudioElement) {
  waveformRef.value?.connectAudio(el)
}

function handleMixedPlay() { isMixedPlaying.value = true }
function handleMixedPause() { isMixedPlaying.value = false }
function handleMixedEnded() { isMixedPlaying.value = false }

async function loadRecent() {
  loadingRecent.value = true
  try {
    const res = await fetch('/api/singing/recent')
    if (res.ok) recentItems.value = await res.json()
  } catch { /* silent */ }
  finally { loadingRecent.value = false }
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

function handleBack() {
  store.reset()
  inputUrl.value = ''
  isMixedPlaying.value = false
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="flex-1 h-full overflow-hidden">
    <h1 class="sr-only">音乐制作</h1>
    <div class="h-full overflow-y-auto">
      <!-- ──── IDLE / ERROR: Centered hero ──── -->
      <div
        v-if="isIdle"
        class="min-h-full flex items-center justify-center p-6"
      >
        <div class="w-full max-w-xl flex flex-col items-center gap-6">
          <!-- Title -->
          <div class="text-center space-y-2">
            <h1 class="text-2xl font-bold text-c-text">
              🎵 音乐制作
            </h1>
            <p class="text-sm text-c-text-dim">
              输入B站视频链接，AI自动完成人声替换
            </p>
          </div>

          <!-- Input + button -->
          <div class="w-full glass p-6 space-y-4">
            <div class="flex gap-3">
              <input
                v-model="inputUrl"
                placeholder="📎 贴上 B站 视频链接..."
                class="flex-1 px-4 py-2.5 rounded-xl bg-c-bg/40 border border-c-border/30
                       text-sm text-c-text placeholder-c-text-dim/50 outline-none
                       focus:border-c-accent/50 transition-all"
                @keyup.enter="startProcess"
              />
              <button
                class="px-5 py-2.5 rounded-xl btn-accent text-sm font-medium whitespace-nowrap"
                :disabled="!inputUrl.trim()"
                :class="{ 'opacity-50 cursor-not-allowed': !inputUrl.trim() }"
                @click="startProcess"
              >
                开始制作
              </button>
            </div>

            <!-- Error message inline -->
            <div
              v-if="store.error"
              class="px-3 py-2 rounded-lg bg-c-error/10 border border-c-error/30 text-xs text-c-error"
            >
              {{ store.error }}
            </div>
          </div>

          <!-- Recent works -->
          <div
            v-if="recentItems.length > 0 || loadingRecent"
            class="w-full space-y-3"
          >
            <div class="text-xs text-c-text-dim font-medium tracking-wide">
              最近作品
            </div>

            <div
              v-if="loadingRecent"
              class="text-xs text-c-text-dim animate-pulse px-1"
            >
              加载中...
            </div>

            <div
              v-for="item in recentItems"
              :key="item.session_id"
              class="flex items-center gap-3 px-3 py-2.5 rounded-xl
                     bg-c-bg/40 border border-c-border/30
                     hover:bg-c-bg/60 hover:border-c-border/50
                     transition-all"
            >
              <button
                class="w-8 h-8 flex items-center justify-center rounded-full
                       bg-c-accent/20 text-c-accent
                       hover:bg-c-accent/40 hover:scale-105
                       transition-all shrink-0"
                :title="'Play ' + item.session_id"
                @click="playRecent(item)"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <polygon points="5,3 19,12 5,21" />
                </svg>
              </button>

              <div class="flex-1 min-w-0">
                <div class="text-xs text-c-text truncate">
                  {{ item.session_id }}
                </div>
                <div class="text-[10px] text-c-text-dim mt-0.5">
                  {{ formatTime(item.duration_sec) }}
                </div>
              </div>

              <a
                :href="item.audio_url"
                class="px-2.5 py-1 rounded-lg bg-c-accent/20 text-c-accent
                       text-xs hover:bg-c-accent/30 transition-all shrink-0"
                target="_blank"
              >
                DL
              </a>

              <a
                v-if="item.subtitle_url"
                :href="item.subtitle_url"
                class="px-2.5 py-1 rounded-lg bg-c-bg/40 text-c-text-dim
                       text-xs hover:text-c-text hover:bg-c-bg/60 transition-all shrink-0"
                target="_blank"
              >
                Sub
              </a>
            </div>
          </div>
        </div>
      </div>

      <!-- ──── NON-IDLE states ──── -->
      <div v-else class="p-6 space-y-6">
        <!-- Processing -->
        <div v-if="isProcessing" class="max-w-xl mx-auto space-y-4">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-bold text-c-text">处理中</h2>
              <span
                class="text-xs text-c-text-dim bg-c-bg/40 px-2 py-0.5 rounded-full font-mono"
              >
                {{ Math.round(store.progress) }}%
              </span>
            </div>
            <button
              class="px-3 py-1.5 rounded-lg bg-c-error/10 text-c-error
                     text-xs hover:bg-c-error/20 transition-all"
              @click="cancel"
            >
              取消
            </button>
          </div>

          <ProcessTimeline
            :current-stage="store.status"
            :progress="store.progress"
          />

          <div
            v-if="store.status === 'waiting_lyrics'"
            class="px-3 py-2 rounded-lg bg-c-gold/10 border border-c-gold/30"
          >
            <span class="text-xs" style="color: #f0c060;">
              歌词已生成，请在 <strong>Aegisub</strong> 中审核时间轴后确认。
            </span>
          </div>
        </div>

        <!-- Error (non-idle context, should be rare) -->
        <div
          v-if="store.error && !isIdle"
          class="max-w-xl mx-auto px-4 py-3 rounded-xl bg-c-error/10 border border-c-error/30"
        >
          <div class="text-sm text-c-error">{{ store.error }}</div>
          <button
            class="mt-2 px-3 py-1 rounded-lg bg-c-bg/40 text-c-text-dim
                   text-xs hover:text-c-text transition-all"
            @click="handleBack"
          >
            返回重试
          </button>
        </div>

        <!-- ──── DONE: Results ──── -->
        <div v-if="hasResult && store.result" class="space-y-6">
          <!-- Top bar -->
          <div class="flex items-center gap-3">
            <button
              class="flex items-center gap-1.5 px-3 py-1.5 rounded-xl
                     bg-c-bg/40 border border-c-border/30
                     text-xs text-c-text-dim hover:text-c-accent
                     hover:border-c-accent/30 transition-all"
              @click="handleBack"
            >
              <svg
                width="14" height="14" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2"
                stroke-linecap="round" stroke-linejoin="round"
              >
                <path d="M19 12H5M12 19l-7-7 7-7" />
              </svg>
              返回
            </button>

            <div
              v-if="store.result.video_title"
              class="text-xs text-c-text-dim truncate flex-1"
            >
              {{ store.result.video_title }}
            </div>
          </div>

          <!-- Three audio player cards -->
          <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <!-- 📻 Original -->
            <div class="glass p-4 space-y-3 flex flex-col">
              <div class="flex items-center gap-2">
                <span class="text-lg">📻</span>
                <div>
                  <div class="text-sm font-medium text-c-text">原音乐</div>
                  <div class="text-[10px] text-c-text-dim">Original B站音频</div>
                </div>
              </div>
              <div class="flex-1">
                <PlaybackControls
                  v-if="store.result.original_url"
                  :duration="store.result.duration"
                  :audio-url="store.result.original_url"
                  @timeupdate="handleTimeupdate"
                />
                <div
                  v-else
                  class="text-xs text-c-text-dim py-4 text-center"
                >
                  不可用
                </div>
              </div>
              <a
                v-if="store.result.original_url"
                :href="store.result.original_url"
                target="_blank"
                class="inline-flex items-center gap-1.5 text-xs text-c-text-dim
                       hover:text-c-accent transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                下载原音乐
              </a>
            </div>

            <!-- 🎵 Replaced + mixed -->
            <div
              class="glass p-4 space-y-3 flex flex-col
                     ring-1 ring-c-border-accent"
            >
              <div class="flex items-center gap-2">
                <span class="text-lg">🎵</span>
                <div>
                  <div class="text-sm font-medium text-c-accent">替换后音乐</div>
                  <div class="text-[10px] text-c-text-dim">RVC替换 + BGM混合</div>
                </div>
              </div>
              <div class="flex-1">
                <PlaybackControls
                  v-if="store.result.audio_url"
                  :duration="store.result.duration"
                  :audio-url="store.result.audio_url"
                  @play="handleMixedPlay"
                  @pause="handleMixedPause"
                  @timeupdate="handleTimeupdate"
                  @audio-ready="handleMixedAudioReady"
                  @ended="handleMixedEnded"
                />
                <div
                  v-else
                  class="text-xs text-c-text-dim py-4 text-center"
                >
                  不可用
                </div>
              </div>
              <a
                v-if="store.result.audio_url"
                :href="store.result.audio_url"
                target="_blank"
                class="inline-flex items-center gap-1.5 text-xs text-c-accent
                       hover:text-c-accent-hover transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                下载混音
              </a>
            </div>

            <!-- 🎤 Vocals only -->
            <div class="glass p-4 space-y-3 flex flex-col">
              <div class="flex items-center gap-2">
                <span class="text-lg">🎤</span>
                <div>
                  <div class="text-sm font-medium text-c-text">替换后纯人声</div>
                  <div class="text-[10px] text-c-text-dim">RVC替换人声（无BGM）</div>
                </div>
              </div>
              <div class="flex-1">
                <PlaybackControls
                  v-if="store.result.vocals_url"
                  :duration="store.result.duration"
                  :audio-url="store.result.vocals_url"
                  @timeupdate="handleTimeupdate"
                />
                <div
                  v-else
                  class="text-xs text-c-text-dim py-4 text-center"
                >
                  不可用
                </div>
              </div>
              <a
                v-if="store.result.vocals_url"
                :href="store.result.vocals_url"
                target="_blank"
                class="inline-flex items-center gap-1.5 text-xs text-c-text-dim
                       hover:text-c-text transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none"
                     stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round"
                >
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                  <polyline points="7 10 12 15 17 10" />
                  <line x1="12" y1="15" x2="12" y2="3" />
                </svg>
                下载纯人声
              </a>
            </div>
          </div>

          <!-- Waveform -->
          <div class="glass p-4">
            <div class="flex items-center gap-2 mb-2">
              <span class="text-xs text-c-text-dim font-medium">波形</span>
            </div>
            <WaveformDisplay
              ref="waveformRef"
              :is-playing="isMixedPlaying"
              :vocals-url="store.result.vocals_url"
            />
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
