<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import Live2DRenderer from '@/components/live2d/Live2DRenderer.vue'
import { useDanmaku } from '@/composables/useDanmaku'
import { useSocket } from '@/composables/useSocket'

// ===== Socket & Composables =====
const { socket } = useSocket()
const { store: danmakuStore, connect: connectDanmaku } = useDanmaku()

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

// ===== Danmaku Room =====
function connectToRoom(): void {
  const params = new URLSearchParams(window.location.search)
  const roomId = params.get('room')
  if (roomId) {
    connectDanmaku(parseInt(roomId, 10))
  }
}

// ===== Toggle =====
function togglePanel(): void {
  isCollapsed.value = !isCollapsed.value
}

// ===== Lifecycle =====
onMounted(() => {
  loadBackground()
  connectToRoom()
})
</script>

<template>
  <div class="live-page">
    <!-- Background -->
    <div
      v-if="bgImage"
      class="bg-layer"
      :style="{ backgroundImage: `url(${bgImage})` }"
    />
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
        <div v-if="danmakuCount === 0" class="empty">
          等待弹幕...
        </div>
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
  background: #0a0a0f;
  font-family: 'Noto Sans SC', sans-serif;
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
  background: linear-gradient(135deg, #1a1028 0%, #2d1b45 50%, #36205a 100%);
}

.vignette {
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse at center, transparent 30%, rgba(10,10,15,0.4) 100%);
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
  background: rgba(10, 10, 15, 0.7);
  backdrop-filter: blur(30px);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 20px;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
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
  color: #f0f0f5;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(240,240,245,0.3);
}

.dot.online {
  background: #4ade80;
  box-shadow: 0 0 8px rgba(74,222,128,0.5);
}

.count {
  font-size: 11px;
  color: rgba(240,240,245,0.4);
  background: rgba(255,255,255,0.04);
  padding: 2px 8px;
  border-radius: 10px;
}

.arrow {
  font-size: 10px;
  color: rgba(240,240,245,0.3);
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
  background: rgba(255,255,255,0.08);
  border-radius: 2px;
}

.msg {
  padding: 8px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  animation: slideIn 0.3s ease;
}

.msg:last-child {
  border-bottom: none;
}

.msg .name {
  font-size: 12px;
  font-weight: 600;
  color: #e879a8;
  margin-right: 6px;
}

.msg .text {
  font-size: 13px;
  color: #f0f0f5;
}

.empty {
  padding: 24px;
  text-align: center;
  font-size: 12px;
  color: rgba(240,240,245,0.3);
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
