<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { useDanmakuStore } from '@/stores/danmaku'
import { useSubtitleStore } from '@/stores/subtitle'
import { useMinecraftStore } from '@/stores/minecraft'
import type { SubtitleDisplayMode, SubtitleFontSize } from '@/stores/subtitle'
import BackgroundSettings from './BackgroundSettings.vue'
import { Events } from '@/constants/socket-events'

const danmakuStore = useDanmakuStore()
const subtitleStore = useSubtitleStore()
const minecraftStore = useMinecraftStore()
const roomInput = ref<number | null>(null)
const roomError = ref('')

function resetLive2dView(): void {
  if (typeof window.__live2dResetView === 'function') {
    window.__live2dResetView()
  }
}

interface ServiceInfo {
  name: string
  value: string
}

interface ConfigData {
  persona: string
  services: Record<string, string>
  active_services: Record<string, string | null>
  system: { host: string; port: number; log_level: string }
  live2d: { model_path: string; enabled: boolean }
  available_personas: string[]
}

const services = ref<ServiceInfo[]>([])
const personaName = ref('')
const modelInfo = ref('')
const backendInfo = ref('')
const loading = ref(true)
const error = ref('')
function handleBilibiliConnect(): void {
  const socket = getSocket()
  if (!socket || !roomInput.value) return
  if (roomInput.value <= 0) {
    roomError.value = '请输入有效的直播间号'
    return
  }
  roomError.value = ''
  danmakuStore.setConnecting(true)
  socket.emit(Events.BILIBILI.CONNECT, { room_id: roomInput.value })
}

function handleBilibiliDisconnect(): void {
  const socket = getSocket()
  if (!socket) return
  socket.emit(Events.BILIBILI.DISCONNECT)
}

const activeSection = ref<'status' | 'background' | 'controls' | 'live' | 'subtitle' | 'theme'>('status')

// Theme toggle
const STORAGE_KEY = 'animetta-theme'
const currentTheme = ref(document.documentElement.className.includes('theme-light') ? 'light' : 'dark')

function setTheme(theme: 'light' | 'dark'): void {
  currentTheme.value = theme
  document.documentElement.className = `theme-${theme}`
  localStorage.setItem(STORAGE_KEY, theme)
}

let cleanup: (() => void) | null = null

onMounted(() => {
  minecraftStore.setupListener()
  const socket = getSocket()
  if (!socket) {
    loading.value = false
    error.value = '未连接后端'
    return
  }

  const handler = (data: ConfigData) => {
    services.value = [
      { name: 'ASR 语音识别', value: data.active_services.asr || data.services.asr || '-' },
      { name: 'TTS 语音合成', value: data.active_services.tts || data.services.tts || '-' },
      { name: 'LLM 语言模型', value: data.active_services.llm || data.services.agent || '-' },
      { name: 'VAD 语音检测', value: data.active_services.vad || data.services.vad || '-' },
    ]
    personaName.value = data.persona || 'neuro-vtuber'
    const modelPath = data.live2d?.model_path || ''
    modelInfo.value = modelPath ? modelPath.split('/').pop() || modelPath : '默认'
    backendInfo.value = `${data.system?.host || 'localhost'}:${data.system?.port || 12394}`
    loading.value = false
  }

  socket.on(Events.CONFIG.DATA, handler)
  cleanup = () => socket.off(Events.CONFIG.DATA, handler)
  socket.emit(Events.CONFIG.GET, {})
})

onUnmounted(() => {
  minecraftStore.teardownListener()
  cleanup?.()
})
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Section tabs -->
    <div class="flex gap-1.5 px-5 py-4 border-b border-c-border/40 shrink-0">
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'status' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'status'"
      >📊 状态</button>
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'background' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'background'"
      >🖼️ 背景</button>
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'controls' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'controls'"
      >🎮 控制</button>
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'live' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'live'"
      >📡 直播</button>
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'subtitle' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'subtitle'"
      >📝 字幕</button>
      <button
        class="px-3 py-1.5 rounded-lg text-xs font-medium transition-all"
        :class="activeSection === 'theme' ? 'bg-c-accent/20 text-c-accent' : 'bg-c-bg/40 text-c-text-dim hover:text-c-text'"
        @click="activeSection = 'theme'"
      >🎨 主题</button>
    </div>

    <!-- Status section -->
    <div v-if="activeSection === 'status'" class="flex-1 overflow-y-auto px-5 py-4">
      <div v-if="loading" class="flex items-center justify-center py-8">
        <span class="text-sm text-c-text-dim animate-pulse">加载配置...</span>
      </div>
      <div v-else-if="error" class="flex items-center justify-center py-8">
        <span class="text-sm text-c-error">{{ error }}</span>
      </div>
      <template v-else>
        <div class="mb-5">
          <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">角色</h3>
          <div class="bg-c-card/50 rounded-xl px-4 py-3 flex items-center gap-2">
            <span class="text-sm">🎭</span>
            <span class="text-sm text-c-text">{{ personaName }}</span>
          </div>
        </div>
        <div class="mb-5">
          <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">Live2D 模型</h3>
          <div class="bg-c-card/50 rounded-xl px-4 py-3 flex items-center gap-2">
            <span class="text-sm">✨</span>
            <span class="text-sm text-c-text truncate" :title="modelInfo">{{ modelInfo }}</span>
          </div>
        </div>
        <div class="mb-4">
          <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">服务配置</h3>
          <div class="space-y-1.5">
            <div v-for="svc in services" :key="svc.name" class="bg-c-card/50 rounded-xl px-3 py-2 flex items-center justify-between">
              <span class="text-xs text-c-text-dim">{{ svc.name }}</span>
              <span class="text-xs text-c-accent font-medium">{{ svc.value }}</span>
            </div>
          </div>
        </div>
        <div class="mb-4">
          <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">后端</h3>
          <div class="bg-c-card/50 rounded-xl px-3 py-2 flex items-center gap-2">
            <span class="text-xs">🖥️</span>
            <span class="text-xs text-c-text-dim">{{ backendInfo }}</span>
          </div>
        </div>
        <div class="pt-4 border-t border-c-border/40">
          <p class="text-10px text-c-text-muted text-center">配置通过 config.yaml 管理 · 重启后生效</p>
        </div>
      </template>
    </div>

    <!-- Background section -->
    <div v-if="activeSection === 'background'" class="flex-1 overflow-y-auto px-5 py-4">
      <BackgroundSettings />
    </div>

    <!-- Controls section -->
    <div v-if="activeSection === 'controls'" class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
      <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">Live2D</h3>
      <button
        class="w-full px-3 py-2.5 rounded-xl bg-c-card/50 text-xs text-c-text hover:bg-c-card transition-colors flex items-center gap-2"
        @click="resetLive2dView()"
      >
        <span>🔄</span>
        <span>重置视图</span>
      </button>
      <p class="text-10px text-c-text-muted">将 Live2D 模型缩放重置为 1x 并居中</p>

      <div class="pt-3 border-t border-c-border/40">
        <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">Minecraft 机器人</h3>
        <p class="text-10px text-c-text-muted mb-3">启动 AI 控制的 Minecraft 角色，可执行挖掘、建造、战斗等操作</p>

        <!-- Connection status -->
        <div class="flex items-center gap-2 mb-3">
          <span
            class="w-2 h-2 rounded-full"
            :class="minecraftStore.connected ? 'bg-c-success shadow-[0_0_6px_rgba(74,222,128,0.6)]' : 'bg-c-error'"
          />
          <span class="text-xs" :class="minecraftStore.connected ? 'text-c-success' : 'text-c-error'">
            {{ minecraftStore.connected ? `已连接 (${minecraftStore.username})` : '已断开' }}
          </span>
          <span v-if="minecraftStore.error" class="text-10px text-c-error ml-1">
            {{ minecraftStore.error }}
          </span>
        </div>

        <!-- Action button -->
        <button
          class="w-full px-3 py-2 rounded-xl text-xs font-medium transition-all flex items-center justify-center gap-1.5"
          :class="minecraftStore.isConnecting
            ? 'bg-c-accent/20 text-c-accent pointer-events-none animate-pulse'
            : minecraftStore.connected
              ? 'bg-c-error/15 text-c-error hover:bg-c-error/25'
              : 'bg-c-accent/15 text-c-accent hover:bg-c-accent/25'"
          :disabled="minecraftStore.isConnecting"
          @click="minecraftStore.connected ? minecraftStore.stop() : minecraftStore.start()"
        >
          <template v-if="minecraftStore.isConnecting">
            <span class="inline-block w-3 h-3 border-2 border-c-accent border-t-transparent rounded-full animate-spin" />
            启动中...
          </template>
          <template v-else>
            {{ minecraftStore.connected ? '⏹ 停止' : '▶ 启动' }}
          </template>
        </button>

        <!-- Viewer spectator section -->
        <div v-if="minecraftStore.connected" class="mt-3 space-y-2">
          <div class="flex items-center gap-2">
            <span
              class="w-2 h-2 rounded-full"
              :class="{
                'bg-c-text-muted': minecraftStore.viewerStatus === 'idle',
                'bg-yellow-400 shadow-[0_0_6px_rgba(250,204,21,0.6)] animate-pulse': minecraftStore.viewerStatus === 'waiting',
                'bg-c-success shadow-[0_0_6px_rgba(74,222,128,0.6)]': minecraftStore.viewerStatus === 'joined',
                'bg-c-error': minecraftStore.viewerStatus === 'left',
              }"
            />
            <span class="text-xs" :class="{
              'text-c-text-muted': minecraftStore.viewerStatus === 'idle',
              'text-yellow-400': minecraftStore.viewerStatus === 'waiting',
              'text-c-success': minecraftStore.viewerStatus === 'joined',
              'text-c-error': minecraftStore.viewerStatus === 'left',
            }">
              <template v-if="minecraftStore.viewerStatus === 'idle'">旁观者: 未配置</template>
              <template v-else-if="minecraftStore.viewerStatus === 'waiting'">等待 {{ minecraftStore.viewerUsername }} 连接...</template>
              <template v-else-if="minecraftStore.viewerStatus === 'joined'">👁 旁观中: {{ minecraftStore.viewerUsername }}</template>
              <template v-else-if="minecraftStore.viewerStatus === 'left'">{{ minecraftStore.viewerUsername }} 已断开</template>
            </span>
          </div>
          <button
            v-if="minecraftStore.viewerStatus !== 'idle'"
            class="w-full px-3 py-1.5 rounded-xl text-xs font-medium transition-all flex items-center justify-center gap-1.5"
            :class="(minecraftStore.viewerStatus === 'joined' || minecraftStore.viewerStatus === 'left')
              ? 'bg-c-accent/15 text-c-accent hover:bg-c-accent/25'
              : 'bg-c-card/50 text-c-text-muted pointer-events-none opacity-50'"
            :disabled="minecraftStore.viewerStatus !== 'joined' && minecraftStore.viewerStatus !== 'left'"
            @click="minecraftStore.spectate()"
          >
            👁 Spectate
          </button>
        </div>
      </div>
    </div>

    <!-- Live streaming section -->
    <div v-if="activeSection === 'live'" class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
      <div>
        <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">Bilibili 直播</h3>
        <p class="text-10px text-c-text-muted mb-3">连接 Bilibili 直播间并接收实时弹幕</p>

        <!-- Room ID input -->
        <div class="space-y-2">
          <label class="text-xs text-c-text-dim">直播间号</label>
          <input
            v-model.number="roomInput"
            type="number"
            min="1"
            placeholder="输入 Bilibili 直播间号"
            class="w-full px-3 py-2 rounded-xl bg-c-bg/60 border border-c-border/40 text-sm text-c-text
                   placeholder:text-c-text-muted focus:outline-none focus:border-c-accent/50 transition-colors"
            :disabled="danmakuStore.isConnecting"
          />
          <p v-if="roomError" class="text-10px text-c-error">{{ roomError }}</p>
        </div>

        <!-- Connection status -->
        <div class="flex items-center gap-2 mt-3 mb-3">
          <span
            class="w-2 h-2 rounded-full"
            :class="danmakuStore.connected ? 'bg-c-success shadow-[0_0_6px_rgba(74,222,128,0.6)]' : 'bg-c-error'"
          />
          <span class="text-xs" :class="danmakuStore.connected ? 'text-c-success' : 'text-c-error'">
            {{ danmakuStore.connected ? '已连接' : '已断开' }}
          </span>
          <span v-if="danmakuStore.statusMessage" class="text-10px text-c-text-muted ml-1">
            {{ danmakuStore.statusMessage }}
          </span>
        </div>

        <!-- Action buttons -->
        <div class="flex gap-2">
          <button
            class="flex-1 px-3 py-2 rounded-xl text-xs font-medium transition-all flex items-center justify-center gap-1.5"
            :class="danmakuStore.isConnecting
              ? 'bg-c-accent/20 text-c-accent pointer-events-none animate-pulse'
              : danmakuStore.connected
                ? 'bg-c-error/15 text-c-error hover:bg-c-error/25'
                : 'bg-c-accent/15 text-c-accent hover:bg-c-accent/25'"
            :disabled="danmakuStore.isConnecting"
            @click="danmakuStore.connected ? handleBilibiliDisconnect() : handleBilibiliConnect()"
          >
            <template v-if="danmakuStore.isConnecting">
              <span class="inline-block w-3 h-3 border-2 border-c-accent border-t-transparent rounded-full animate-spin" />
              连接中...
            </template>
            <template v-else>
              {{ danmakuStore.connected ? '🔌 断开连接' : '🔗 连接' }}
            </template>
          </button>
        </div>
      </div>

      <div class="pt-3 border-t border-c-border/40 space-y-2">
        <h4 class="text-10px font-medium text-c-text-dim uppercase tracking-wider">弹幕统计</h4>
        <div class="bg-c-card/50 rounded-xl px-3 py-2 flex items-center justify-between">
          <span class="text-xs text-c-text-dim">已接收弹幕</span>
          <span class="text-xs text-c-accent font-medium tabular-nums">{{ danmakuStore.messageCount }} 条</span>
        </div>
      </div>
    </div>

    <!-- Subtitle section -->
    <div v-if="activeSection === 'subtitle'" class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
      <div>
        <h3 class="text-sm font-medium text-c-text-dim uppercase tracking-wider mb-3">📝 字幕设置</h3>
        <p class="text-10px text-c-text-muted mb-3">在 Live2D 画布底部显示 AI 回复字幕，支持双语展示</p>

        <!-- Enable toggle -->
        <div class="flex items-center justify-between bg-c-card/50 rounded-xl px-4 py-3 mb-3">
          <span class="text-xs text-c-text">启用字幕</span>
          <button
            class="w-10 h-5 rounded-full transition-colors relative"
            :class="subtitleStore.enabled ? 'bg-c-accent' : 'bg-c-bg/60 border border-c-border/40'"
            @click="subtitleStore.toggle()"
          >
            <span
              class="absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform"
              :class="subtitleStore.enabled ? 'translate-x-[22px]' : 'translate-x-[2px]'"
            />
          </button>
        </div>

        <!-- Display mode -->
        <div class="mb-3">
          <label class="text-xs text-c-text-dim block mb-2">显示模式</label>
          <div class="flex gap-2">
            <button
              v-for="mode in ([
                { key: 'original' as const, label: '原文', icon: '🈶' },
                { key: 'translated' as const, label: '翻译', icon: '🈳' },
                { key: 'bilingual' as const, label: '双语', icon: '🌐' }
              ])"
              :key="mode.key"
              class="flex-1 px-2 py-2 rounded-xl text-10px font-medium transition-all"
              :class="subtitleStore.displayMode === mode.key
                ? 'bg-c-accent/20 text-c-accent border border-c-accent/30'
                : 'bg-c-card/50 text-c-text-dim hover:bg-c-card border border-transparent'"
              @click="subtitleStore.setDisplayMode(mode.key)"
            >
              {{ mode.icon }} {{ mode.label }}
            </button>
          </div>
        </div>

        <!-- Font size -->
        <div class="mb-3">
          <label class="text-xs text-c-text-dim block mb-2">字体大小</label>
          <div class="flex gap-2">
            <button
              v-for="size in ([
                { key: 'small' as const, label: '小 (1.5rem)' },
                { key: 'medium' as const, label: '中 (2rem)' },
                { key: 'large' as const, label: '大 (2.5rem)' }
              ])"
              :key="size.key"
              class="flex-1 px-2 py-2 rounded-xl text-10px font-medium transition-all"
              :class="subtitleStore.fontSize === size.key
                ? 'bg-c-accent/20 text-c-accent border border-c-accent/30'
                : 'bg-c-card/50 text-c-text-dim hover:bg-c-card border border-transparent'"
              @click="subtitleStore.setFontSize(size.key)"
            >
              {{ size.label }}
            </button>
          </div>
        </div>

        <!-- Reset position -->
        <div class="mb-3" v-if="subtitleStore.posX != null || subtitleStore.posY != null">
          <button
            class="w-full px-3 py-2 rounded-xl text-xs font-medium transition-all
                   bg-c-card/50 text-c-text-dim hover:bg-c-card border border-transparent
                   flex items-center justify-center gap-2"
            @click="subtitleStore.resetPosition()"
          >
            🔄 重置字幕位置（归位到底部居中）
          </button>
        </div>

        <!-- Target language -->
        <div>
          <label class="text-xs text-c-text-dim block mb-2">翻译目标语言</label>
          <select
            :value="subtitleStore.targetLanguage"
            class="w-full px-3 py-2 rounded-xl bg-c-bg/60 border border-c-border/40 text-sm text-c-text
                   focus:outline-none focus:border-c-accent/50 transition-colors appearance-none cursor-pointer"
            @change="(e) => {
              const lang = (e.target as HTMLSelectElement).value
              subtitleStore.setTargetLanguage(lang)
              const socket = getSocket()
              if (socket) socket.emit(Events.TRANSLATION.CONFIGURE, { target_language: lang })
            }"
          >
            <option value="English">English (英语)</option>
            <option value="日本語">日本語 (日语)</option>
            <option value="한국어">한국어 (韩语)</option>
            <option value="中文">中文 (Chinese)</option>
            <option value="Français">Français (法语)</option>
            <option value="Deutsch">Deutsch (德语)</option>
            <option value="Español">Español (西班牙语)</option>
            <option value="Русский">Русский (俄语)</option>
          </select>
        </div>
      </div>
    </div>

    <!-- Theme section -->
    <div v-if="activeSection === 'theme'" class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
      <div class="mb-5">
        <h3 class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-3">外观模式</h3>
        <div class="grid grid-cols-2 gap-3">
          <button
            class="flex flex-col items-center gap-2 p-4 rounded-xl border transition-all"
            :class="currentTheme === 'dark'
              ? 'border-c-accent bg-c-accent/10'
              : 'border-c-border bg-c-card/50 hover:border-c-border-accent'"
            @click="setTheme('dark')"
          >
            <span class="text-2xl">🌙</span>
            <span class="text-xs font-medium" :class="currentTheme === 'dark' ? 'text-c-accent' : 'text-c-text-dim'">暗色模式</span>
            <span class="text-10px text-c-text-muted">日系赛博夜晚</span>
          </button>
          <button
            class="flex flex-col items-center gap-2 p-4 rounded-xl border transition-all"
            :class="currentTheme === 'light'
              ? 'border-c-accent bg-c-accent/10'
              : 'border-c-border bg-c-card/50 hover:border-c-border-accent'"
            @click="setTheme('light')"
          >
            <span class="text-2xl">☀️</span>
            <span class="text-xs font-medium" :class="currentTheme === 'light' ? 'text-c-accent' : 'text-c-text-dim'">亮色模式</span>
            <span class="text-10px text-c-text-muted">AIRI 柔和白昼</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
::-webkit-scrollbar { width: 3px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
</style>
