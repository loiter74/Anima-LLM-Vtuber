<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import Live2DRenderer from '@/components/live2d/Live2DRenderer.vue'
import { useDanmaku } from '@/composables/useDanmaku'
import { useSocket } from '@/composables/useSocket'

// ===== Socket & Composables =====
useSocket()
const { store: danmakuStore } = useDanmaku({ canControl: false })

// ===== State =====
const isCollapsed = ref(false)
const bgImage = ref('')

// ===== Computed =====
const danmakuCount = computed(() => danmakuStore.messages.length)
const lastMessages = computed(() => danmakuStore.messages.slice(-50))
const wsConnected = computed(() => danmakuStore.connected)

// ===== Background =====
function loadBackground(): void {
  const params = new URLSearchParams(window.location.search)
  const bg = params.get('bg')
  if (bg) {
    bgImage.value = `/backgrounds/${bg}`
  }
}

// ===== Toggle =====
function togglePanel(): void {
  isCollapsed.value = !isCollapsed.value
}

// ===== Lifecycle =====
onMounted(() => {
  loadBackground()
})
</script>

<template>
  <div class="live-page">
    <!-- Background -->
    <div v-if="bgImage" class="bg-layer" :style="{ backgroundImage: `url(${bgImage})` }" />
    <div v-else class="bg-gradient" />

    <!-- Vignette -->
    <div class="vignette" />

    <!-- Live2D (full screen) -->
    <div class="live2d-layer">
      <Live2DRenderer />
    </div>

    <!-- Danmaku Panel -->
    <div class="danmaku" :class="{ collapsed: isCollapsed }">
      <div class="danmaku-header" @click="togglePanel">
        <div class="danmaku-title">
          <div class="dot" :class="{ online: wsConnected }" />
          <span>弹幕</span>
        </div>
        <span class="count">{{ danmakuCount }}</span>
        <span class="arrow">{{ isCollapsed ? '▶' : '▼' }}</span>
      </div>

      <div v-if="!isCollapsed" class="danmaku-list">
        <div v-for="(msg, i) in lastMessages" :key="i" class="msg">
          <span class="name">{{ msg.user_name }}</span>
          <span class="text">{{ msg.text }}</span>
        </div>
        <div v-if="danmakuCount === 0" class="empty">等待弹幕...</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.live-page {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--c-bg);
  font-family: var(--font-sans);
}

/* Background */
.bg-layer {
  position: absolute;
  inset: 0;
  background-size: cover;
  background-position: center;
}

.bg-gradient {
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, var(--c-bg) 0%, var(--c-panel) 50%, var(--c-card) 100%);
}

.vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(
    ellipse at center,
    transparent 30%,
    color-mix(in srgb, var(--c-bg) 40%, transparent) 100%
  );
  pointer-events: none;
  z-index: 1;
}

/* Live2D */
.live2d-layer {
  position: absolute;
  inset: 0;
  z-index: 10;
}

/* Danmaku */
.danmaku {
  position: absolute;
  top: 24px;
  left: 24px;
  z-index: 20;
  width: 320px;
  max-height: 500px;
  background: color-mix(in srgb, var(--c-bg) 70%, transparent);
  backdrop-filter: blur(30px);
  border: 1px solid var(--c-border);
  border-radius: var(--r-2xl);
  overflow: hidden;
  transition: all var(--d-slow) var(--ease-out-expo);
}

.danmaku.collapsed {
  width: 120px;
  max-height: 44px;
}

.danmaku-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
}

.danmaku-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--c-text-muted);
}

.dot.online {
  background: var(--c-success);
  box-shadow: var(--shadow-glow-success);
}

.count {
  font-size: 11px;
  color: var(--c-text-muted);
  background: color-mix(in srgb, var(--c-border) 50%, transparent);
  padding: 2px 8px;
  border-radius: 10px;
}

.arrow {
  font-size: 10px;
  color: var(--c-text-muted);
}

.danmaku-list {
  max-height: 420px;
  overflow-y: auto;
  padding: 0 16px 12px;
}

.danmaku-list::-webkit-scrollbar {
  width: 3px;
}

.danmaku-list::-webkit-scrollbar-thumb {
  background: var(--c-border);
  border-radius: 2px;
}

.msg {
  padding: 8px 0;
  border-bottom: 1px solid var(--c-border);
  animation: slideIn var(--d-slow) var(--ease-out-expo);
}

.msg:last-child {
  border-bottom: none;
}

.msg .name {
  font-size: 12px;
  font-weight: 600;
  color: var(--c-accent);
  margin-right: 6px;
}

.msg .text {
  font-size: 13px;
  color: var(--c-text);
}

.empty {
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: var(--c-text-muted);
}

@keyframes slideIn {
  from {
    opacity: 0;
    transform: translateY(8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
