<script setup lang="ts">
import { ref } from 'vue'
import ChatPanel from '@/components/chat/ChatPanel.vue'
import LiveChatPanel from '@/components/chat/LiveChatPanel.vue'
import SettingsPanel from '@/components/settings/SettingsPanel.vue'
import MemoryPanel from '@/components/memory/MemoryPanel.vue'
import PersonalityPanel from '@/components/personality/PersonalityPanel.vue'
import MusicCard from '@/components/singing/MusicCard.vue'
import PopOutButton from '@/components/live2d/PopOutButton.vue'
import { useDanmaku } from '@/composables/useDanmaku'
import { useMobile } from '@/composables/useMobile'

const props = defineProps<{
  live2dPopout: boolean
}>()

const emit = defineEmits<{
  popout: []
  popoutClosed: []
}>()

const { isMobile } = useMobile()
const isCollapsed = ref(false)
const activeTab = ref<'chat' | 'live' | 'memory' | 'personality' | 'singing' | 'settings'>('chat')

// Mobile tab definitions (icon-only)
const mobileTabs = [
  { key: 'chat' as const, icon: '💬', label: '聊天' },
  { key: 'live' as const, icon: '📺', label: '直播' },
  { key: 'memory' as const, icon: '🧠', label: '记忆' },
  { key: 'personality' as const, icon: '🎭', label: '人格' },
  { key: 'singing' as const, icon: '🎵', label: '音乐' },
  { key: 'settings' as const, icon: '⚙️', label: '设置' },
]

// Desktop tab labels
const desktopTabLabels: Record<string, string> = {
  chat: '💬 聊天', live: '📺 直播', memory: '🧠 记忆',
  personality: '🎭 人格', singing: '🎵 音乐', settings: '⚙️ 设置',
}

// Initialize danmaku socket listeners (runs globally, not per-tab)
useDanmaku()
</script>

<template>
  <!-- ========== MOBILE LAYOUT ========== -->
  <div v-if="isMobile" class="mobile-interactive-panel flex flex-col h-full pointer-events-none">
    <!-- Mobile: panel content -->
    <div class="flex-1 overflow-hidden relative pointer-events-auto">
      <Transition name="fade" mode="out-in">
        <ChatPanel v-if="activeTab === 'chat'" key="chat" />
        <LiveChatPanel v-else-if="activeTab === 'live'" key="live" />
        <MemoryPanel v-else-if="activeTab === 'memory'" key="memory" />
        <PersonalityPanel v-else-if="activeTab === 'personality'" key="personality" />
        <MusicCard v-else-if="activeTab === 'singing'" key="singing" />
        <SettingsPanel v-else key="settings" />
      </Transition>
    </div>

    <!-- Mobile: fixed bottom navigation bar -->
    <nav
      data-testid="mobile-tabbar"
      class="mobile-tabbar shrink-0 pointer-events-auto grid grid-cols-6 items-center gap-1 p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] bg-c-surface/90 backdrop-blur-xl border-t border-c-border"
    >
      <button
        v-for="tab in mobileTabs"
        :key="tab.key"
        data-testid="mobile-tab-button"
        class="mobile-tab-button flex-1 min-w-0 flex flex-col items-center gap-0.5 px-1.5 py-1.5 rounded-xl transition-all touch-manipulation"
        :class="activeTab === tab.key
          ? 'bg-c-accent/20 text-c-accent'
          : 'text-c-text-dim active:text-c-accent'"
        @click="activeTab = tab.key"
      >
        <span class="text-lg leading-none">{{ tab.icon }}</span>
        <span class="text-9px leading-tight">{{ tab.label }}</span>
      </button>
    </nav>
  </div>

  <!-- ========== DESKTOP LAYOUT ========== -->
  <div v-else class="panel-container">
    <!-- Header: Tabs + Collapse -->
    <div class="panel-header">
      <div class="panel-tabs">
        <button
          v-for="tab in (['chat', 'live', 'memory', 'personality', 'singing', 'settings'] as const)"
          :key="tab"
          :aria-label="desktopTabLabels[tab]"
          class="panel-tab"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ desktopTabLabels[tab] }}
        </button>
      </div>

      <!-- PopOut button -->
      <PopOutButton
        v-if="!live2dPopout"
        class="mr-1"
        @popout="emit('popout')"
      />

      <!-- Collapse button -->
      <button
        class="panel-collapse"
        aria-label="收起侧边栏"
        @click="isCollapsed = true"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7" />
        </svg>
      </button>
    </div>

    <!-- Tab content -->
    <div class="panel-content">
      <Transition name="fade" mode="out-in">
        <ChatPanel v-if="activeTab === 'chat'" key="chat" />
        <LiveChatPanel v-else-if="activeTab === 'live'" key="live" />
        <MemoryPanel v-else-if="activeTab === 'memory'" key="memory" />
        <PersonalityPanel v-else-if="activeTab === 'personality'" key="personality" />
        <MusicCard v-else-if="activeTab === 'singing'" key="singing" />
        <SettingsPanel v-else key="settings" />
      </Transition>
    </div>
  </div>
</template>

<style scoped>
.mobile-interactive-panel {
  contain: layout paint;
}

.mobile-tabbar {
  min-height: 58px;
}

.mobile-tab-button {
  min-height: 42px;
}

/* Desktop Panel Container */
.panel-container {
  width: 340px;
  background: rgba(36, 21, 56, 0.85);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  border: 1px solid var(--c-border);
  border-radius: var(--r-2xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex-shrink: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  padding: var(--s-4) var(--s-5);
  border-bottom: 1px solid var(--c-border);
  flex-shrink: 0;
}

.panel-tabs {
  display: flex;
  gap: var(--s-1);
  flex: 1;
  overflow-x: auto;
}

.panel-tab {
  padding: var(--s-1_5) var(--s-3);
  font-size: 12px;
  font-weight: 500;
  color: var(--c-text-dim);
  background: rgba(26, 16, 40, 0.40);
  border: none;
  border-radius: var(--r-lg);
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
  white-space: nowrap;
  font-family: inherit;
}

.panel-tab:hover {
  color: var(--c-text);
  background: rgba(45, 27, 69, 0.60);
}

.panel-tab.active {
  color: var(--c-accent);
  background: var(--c-accent-soft);
}

.panel-collapse {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(26, 16, 40, 0.40);
  border: none;
  border-radius: var(--r-lg);
  color: var(--c-text-dim);
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
  flex-shrink: 0;
}

.panel-collapse:hover {
  color: var(--c-text);
  background: rgba(26, 16, 40, 0.60);
}

.panel-content {
  flex: 1;
  overflow: hidden;
  position: relative;
}

/* Transitions */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* Scrollbar */
.panel-content::-webkit-scrollbar {
  width: 6px;
}

.panel-content::-webkit-scrollbar-track {
  background: transparent;
}

.panel-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.10);
  border-radius: 3px;
}

.panel-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
