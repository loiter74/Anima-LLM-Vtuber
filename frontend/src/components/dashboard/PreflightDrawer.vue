<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useDanmaku } from '@/composables/useDanmaku'
import { getSocket } from '@/composables/useSocket'
import { Events } from '@/constants/socket-events'
import BackgroundSettings from '@/components/settings/BackgroundSettings.vue'
import SectionTabs, { type SectionTab } from '@/components/shared/SectionTabs.vue'
import { fetchRuntimeStatus } from '@/services/runtimeStatus'
import type { ProviderIdentity, RuntimeServiceStatus } from '@/types/runtime-status'
import { useDanmakuStore } from '@/stores/danmaku'
import { useMinecraftStore } from '@/stores/minecraft'
import { usePersonalityStore } from '@/stores/personality'
import {
  useSubtitleStore,
  type SubtitleDisplayMode,
  type SubtitleFontSize,
} from '@/stores/subtitle'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()

const drawerRef = ref<HTMLElement | null>(null)
const closeButtonRef = ref<HTMLButtonElement | null>(null)
const activeSection = ref('connection')
const runtimeLoading = ref(false)
const runtimeError = ref('')
const services = ref<Array<{ name: string; ready: boolean; identity: string; reason: string }>>([])
const roomInput = ref<number | null>(null)
const roomError = ref('')
const selectedPersona = ref('')

const danmakuStore = useDanmakuStore()
const minecraftStore = useMinecraftStore()
const personalityStore = usePersonalityStore()
const subtitleStore = useSubtitleStore()
const { connect, disconnect, updateRoom } = useDanmaku({ listen: false })

const sections: readonly SectionTab[] = [
  { id: 'connection', label: '连接', description: '服务、Bilibili 和 Minecraft 生命周期' },
  { id: 'persona', label: '人格', description: '人设、流式模式和记忆影响度' },
  { id: 'presentation', label: '画面', description: '背景、字幕、视图和控制台主题' },
]

function formatIdentity(value: ProviderIdentity): string {
  return (
    [value.provider ?? value.type, value.model, value.voice].filter(Boolean).join(' · ') || '未配置'
  )
}

function identity(status: RuntimeServiceStatus): string {
  return formatIdentity(status.resolved ?? status.configured)
}

async function loadRuntime(): Promise<void> {
  runtimeLoading.value = true
  runtimeError.value = ''
  try {
    const status = await fetchRuntimeStatus()
    services.value = [
      ['LLM', status.components.llm],
      ['ASR', status.components.asr],
      ['TTS', status.components.tts],
      ['VAD', status.components.vad],
    ].map(([name, service]) => {
      const typed = service as (typeof status.components)['llm']
      return {
        name: String(name),
        ready: typed.ready,
        identity: identity(typed),
        reason: typed.reason || '',
      }
    })
  } catch (cause) {
    runtimeError.value = cause instanceof Error ? cause.message : '运行状态读取失败'
  } finally {
    runtimeLoading.value = false
  }
}

async function applyRoom(): Promise<void> {
  if (!roomInput.value || roomInput.value <= 0) {
    roomError.value = '请输入有效的直播间号'
    return
  }
  const command =
    danmakuStore.desiredRoomId && danmakuStore.desiredRoomId !== roomInput.value
      ? updateRoom
      : connect
  const ack = await command(roomInput.value)
  roomError.value = ack.accepted ? '' : ack.message
}

async function disconnectRoom(): Promise<void> {
  const ack = await disconnect()
  roomError.value = ack.accepted ? '' : ack.message
}

async function applyPersona(): Promise<void> {
  if (selectedPersona.value) await personalityStore.setPersona(selectedPersona.value)
}

function updateSubtitle(): void {
  getSocket()?.emit(Events.TRANSLATION.CONFIGURE, {
    enabled: subtitleStore.enabled,
    target_language: subtitleStore.targetLanguage,
  })
}

function toggleSubtitle(): void {
  subtitleStore.toggle()
  updateSubtitle()
}

function setDisplayMode(event: Event): void {
  subtitleStore.setDisplayMode((event.target as HTMLSelectElement).value as SubtitleDisplayMode)
}

function setFontSize(event: Event): void {
  subtitleStore.setFontSize((event.target as HTMLSelectElement).value as SubtitleFontSize)
}

function setTargetLanguage(event: Event): void {
  subtitleStore.setTargetLanguage((event.target as HTMLSelectElement).value)
  updateSubtitle()
}

function resetLive2dView(): void {
  window.__live2dResetView?.()
}

function setTheme(theme: 'dark' | 'light'): void {
  document.documentElement.classList.toggle('theme-light', theme === 'light')
  localStorage.setItem('animetta-theme', theme)
}

function close(): void {
  emit('close')
}

function trapFocus(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  if (event.key !== 'Tab' || !drawerRef.value) return
  const focusable = Array.from(
    drawerRef.value.querySelectorAll<HTMLElement>(
      'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  )
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first?.focus()
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    roomInput.value = danmakuStore.desiredRoomId ?? danmakuStore.roomId
    selectedPersona.value = personalityStore.currentPersona ?? ''
    void loadRuntime()
    void personalityStore.fetchAvailablePersonas()
    minecraftStore.refreshStatus()
    await nextTick()
    closeButtonRef.value?.focus()
  },
)

watch(
  () => personalityStore.currentPersona,
  (persona) => {
    if (!selectedPersona.value && persona) selectedPersona.value = persona
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex justify-end bg-c-bg/70 backdrop-blur-sm"
        @click.self="close"
      >
        <aside
          ref="drawerRef"
          class="flex h-full w-full max-w-2xl flex-col border-l border-c-border bg-c-surface shadow-2xl"
          role="dialog"
          aria-modal="true"
          aria-labelledby="preflight-title"
          @keydown="trapFocus"
        >
          <header
            class="flex shrink-0 items-start justify-between gap-4 border-b border-c-border px-5 py-4"
          >
            <div>
              <h1 id="preflight-title" class="text-base font-semibold">开播准备</h1>
              <p class="mt-1 text-xs text-c-text-muted">连接、人格和画面设置集中在此处</p>
            </div>
            <button
              ref="closeButtonRef"
              class="btn-ghost"
              type="button"
              aria-label="关闭开播准备"
              @click="close"
            >
              关闭
            </button>
          </header>

          <SectionTabs v-model="activeSection" :tabs="sections" label="开播准备分区" />

          <div class="min-h-0 flex-1 overflow-y-auto p-5">
            <section
              v-if="activeSection === 'connection'"
              id="开播准备分区-connection-panel"
              role="tabpanel"
              aria-labelledby="开播准备分区-connection-tab"
              class="space-y-4"
            >
              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <div class="flex items-center justify-between gap-3">
                  <h2 class="text-sm font-semibold">核心服务</h2>
                  <button
                    class="btn-ghost"
                    type="button"
                    :disabled="runtimeLoading"
                    @click="loadRuntime"
                  >
                    刷新状态
                  </button>
                </div>
                <p v-if="runtimeError" class="mt-3 text-xs text-c-error" role="alert">
                  {{ runtimeError }}
                </p>
                <div class="mt-3 grid gap-2 sm:grid-cols-2">
                  <article
                    v-for="service in services"
                    :key="service.name"
                    class="rounded-xl border border-c-border bg-c-card/45 p-3"
                  >
                    <div class="flex items-center justify-between gap-2">
                      <h3 class="text-xs font-medium">{{ service.name }}</h3>
                      <span
                        class="text-10px"
                        :class="service.ready ? 'text-c-success' : 'text-c-error'"
                        >{{ service.ready ? '就绪' : '不可用' }}</span
                      >
                    </div>
                    <p class="mt-2 truncate font-mono text-10px text-c-text-muted">
                      {{ service.identity }}
                    </p>
                    <p v-if="service.reason" class="mt-1 text-10px text-c-warning">
                      {{ service.reason }}
                    </p>
                  </article>
                </div>
              </div>

              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <h2 class="text-sm font-semibold">Bilibili 房间</h2>
                <p class="mt-1 text-xs text-c-text-muted">
                  {{ danmakuStore.statusMessage || danmakuStore.state }}
                </p>
                <div class="mt-3 flex flex-wrap gap-2">
                  <input
                    v-model.number="roomInput"
                    type="number"
                    min="1"
                    class="min-w-40 flex-1 rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm outline-none focus:border-c-border-accent"
                    placeholder="直播间号"
                  />
                  <button
                    class="btn-accent"
                    type="button"
                    :disabled="danmakuStore.isConnecting"
                    @click="applyRoom"
                  >
                    {{ danmakuStore.connected ? '切换房间' : '连接房间' }}
                  </button>
                  <button
                    class="btn-ghost"
                    type="button"
                    :disabled="!danmakuStore.connected"
                    @click="disconnectRoom"
                  >
                    断开
                  </button>
                </div>
                <p v-if="roomError" class="mt-2 text-xs text-c-error" role="alert">
                  {{ roomError }}
                </p>
              </div>

              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <div class="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h2 class="text-sm font-semibold">Minecraft 托管栈</h2>
                    <p class="mt-1 text-xs text-c-text-muted">
                      {{ minecraftStore.lifecycleState }} · Bot
                      {{ minecraftStore.botLifecycleState }} · 旁观者
                      {{ minecraftStore.viewerBindingState }}
                    </p>
                  </div>
                  <span
                    class="rounded-lg px-2 py-1 text-10px"
                    :class="
                      minecraftStore.connected
                        ? 'bg-c-success/10 text-c-success'
                        : 'bg-c-panel text-c-text-muted'
                    "
                    >{{ minecraftStore.connected ? '已就绪' : '未连接' }}</span
                  >
                </div>
                <div class="mt-3 flex flex-wrap gap-2">
                  <button
                    class="btn-accent"
                    type="button"
                    :disabled="minecraftStore.isConnecting || minecraftStore.connected"
                    @click="minecraftStore.connect()"
                  >
                    启动并连接
                  </button>
                  <button
                    class="btn-ghost"
                    type="button"
                    :disabled="!minecraftStore.connected"
                    @click="minecraftStore.disconnect()"
                  >
                    断开 Bot
                  </button>
                  <button class="btn-ghost" type="button" @click="minecraftStore.reattachViewer()">
                    重连旁观者
                  </button>
                  <button
                    class="btn-ghost text-c-error"
                    type="button"
                    :disabled="minecraftStore.lifecycleState === 'stopped'"
                    @click="minecraftStore.shutdown()"
                  >
                    停止托管栈
                  </button>
                </div>
                <p v-if="minecraftStore.error" class="mt-2 text-xs text-c-error">
                  {{ minecraftStore.error }}
                </p>
              </div>
            </section>

            <section
              v-else-if="activeSection === 'persona'"
              id="开播准备分区-persona-panel"
              role="tabpanel"
              aria-labelledby="开播准备分区-persona-tab"
              class="space-y-4"
            >
              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <h2 class="text-sm font-semibold">直播人设</h2>
                <div class="mt-3 flex flex-wrap gap-2">
                  <select
                    v-model="selectedPersona"
                    class="min-w-48 flex-1 rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm"
                  >
                    <option
                      v-for="persona in personalityStore.availablePersonas"
                      :key="persona"
                      :value="persona"
                    >
                      {{ persona }}
                    </option>
                  </select>
                  <button
                    class="btn-accent"
                    type="button"
                    :disabled="!selectedPersona || personalityStore.personaLoading"
                    @click="applyPersona"
                  >
                    应用人设
                  </button>
                </div>
                <p v-if="personalityStore.personaError" class="mt-2 text-xs text-c-error">
                  {{ personalityStore.personaError }}
                </p>
              </div>
              <div class="grid gap-4 sm:grid-cols-2">
                <label class="rounded-xl border border-c-border bg-c-panel/35 p-4 text-xs">
                  <span class="text-c-text-muted">运行模式</span>
                  <select
                    :value="personalityStore.currentMode"
                    class="mt-2 w-full rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm"
                    @change="
                      personalityStore.setMode(
                        ($event.target as HTMLSelectElement).value as 'default' | 'streaming',
                      )
                    "
                  >
                    <option value="default">默认</option>
                    <option value="streaming">直播流式</option>
                  </select>
                </label>
                <label class="rounded-xl border border-c-border bg-c-panel/35 p-4 text-xs">
                  <span class="text-c-text-muted"
                    >记忆影响度 {{ Math.round(personalityStore.memoryInfluence * 100) }}%</span
                  >
                  <input
                    :value="personalityStore.memoryInfluence"
                    class="mt-4 w-full accent-c-accent"
                    type="range"
                    min="0"
                    max="1"
                    step="0.05"
                    @input="
                      personalityStore.setMemoryInfluence(
                        Number(($event.target as HTMLInputElement).value),
                      )
                    "
                  />
                </label>
              </div>
              <dl class="grid gap-3 sm:grid-cols-2">
                <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                  <dt class="text-xs text-c-text-muted">当前情绪</dt>
                  <dd class="mt-2 text-sm">{{ personalityStore.currentMood || '未报告' }}</dd>
                </div>
                <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                  <dt class="text-xs text-c-text-muted">MBTI</dt>
                  <dd class="mt-2 font-mono text-sm">
                    {{ personalityStore.mbtiType || '未报告' }}
                  </dd>
                </div>
              </dl>
            </section>

            <section
              v-else
              id="开播准备分区-presentation-panel"
              role="tabpanel"
              aria-labelledby="开播准备分区-presentation-tab"
              class="space-y-4"
            >
              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <h2 class="text-sm font-semibold">直播背景</h2>
                <div class="mt-3"><BackgroundSettings /></div>
              </div>
              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <div class="flex items-center justify-between gap-3">
                  <h2 class="text-sm font-semibold">字幕</h2>
                  <button
                    class="btn-ghost"
                    type="button"
                    :aria-pressed="subtitleStore.enabled"
                    @click="toggleSubtitle"
                  >
                    {{ subtitleStore.enabled ? '已启用' : '已关闭' }}
                  </button>
                </div>
                <div class="mt-3 grid gap-3 sm:grid-cols-3">
                  <label class="text-xs text-c-text-muted"
                    >显示模式<select
                      :value="subtitleStore.displayMode"
                      class="mt-2 w-full rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm text-c-text"
                      @change="setDisplayMode"
                    >
                      <option value="original">原文</option>
                      <option value="translated">译文</option>
                      <option value="bilingual">双语</option>
                    </select></label
                  >
                  <label class="text-xs text-c-text-muted"
                    >字号<select
                      :value="subtitleStore.fontSize"
                      class="mt-2 w-full rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm text-c-text"
                      @change="setFontSize"
                    >
                      <option value="small">小</option>
                      <option value="medium">中</option>
                      <option value="large">大</option>
                    </select></label
                  >
                  <label class="text-xs text-c-text-muted"
                    >目标语言<input
                      :value="subtitleStore.targetLanguage"
                      class="mt-2 w-full rounded-xl border border-c-border bg-c-card/55 px-3 py-2 text-sm text-c-text"
                      @change="setTargetLanguage"
                  /></label>
                </div>
                <button class="btn-ghost mt-3" type="button" @click="subtitleStore.resetPosition()">
                  重置字幕位置
                </button>
              </div>
              <div class="rounded-xl border border-c-border bg-c-panel/35 p-4">
                <h2 class="text-sm font-semibold">视图与主题</h2>
                <div class="mt-3 flex flex-wrap gap-2">
                  <button class="btn-ghost" type="button" @click="resetLive2dView">
                    重置 Live2D 视图
                  </button>
                  <button class="btn-ghost" type="button" @click="setTheme('dark')">
                    深色控制台
                  </button>
                  <button class="btn-ghost" type="button" @click="setTheme('light')">
                    亮色控制台
                  </button>
                </div>
              </div>
            </section>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 200ms var(--ease-out-expo);
}
.drawer-enter-active aside,
.drawer-leave-active aside {
  transition: transform 300ms var(--ease-out-expo);
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from aside,
.drawer-leave-to aside {
  transform: translateX(100%);
}
@media (prefers-reduced-motion: reduce) {
  .drawer-enter-active,
  .drawer-leave-active,
  .drawer-enter-active aside,
  .drawer-leave-active aside {
    transition-duration: 0ms;
  }
}
</style>
