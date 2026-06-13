<script setup lang="ts">
import { useRouter, useRoute } from 'vue-router'
import { useConnectionStore } from '@/stores/connection'

const router = useRouter()
const route = useRoute()
const store = useConnectionStore()

const statusColors: Record<string, string> = {
  connected: 'bg-c-success shadow-[0_0_8px_rgba(74,222,128,0.6)]',
  disconnected: 'bg-c-error',
  connecting: 'bg-c-warning animate-pulse',
  error: 'bg-c-error'
}

const statusLabels: Record<string, string> = {
  connected: 'Connected',
  disconnected: 'Disconnected',
  connecting: 'Connecting...',
  error: 'Connection Error'
}

function goTo(name: string) {
  if (route.name === name) {
    router.push('/')
  } else {
    router.push('/' + (name === 'chat' ? '' : name))
  }
}
</script>

<template>
  <header class="titlebar">
    <!-- Left: traffic lights + brand -->
    <div class="titlebar-left">
      <div class="traffic-lights">
        <span class="close"></span>
        <span class="minimize"></span>
        <span class="maximize"></span>
      </div>
      <div class="brand">Anima<span class="brand-dot">.</span></div>
    </div>

    <!-- Center: nav buttons -->
    <div class="titlebar-center">
      <button
        @click="goTo('music')"
        class="nav-btn"
        :class="{ active: route.name === 'music' }"
      >
        Music
      </button>
      <button
        @click="goTo('meme-review')"
        class="nav-btn"
        :class="{ active: route.name === 'meme-review' }"
      >
        Meme
      </button>
      <button
        @click="goTo('dashboard')"
        class="nav-btn"
        :class="{ active: route.name === 'dashboard' }"
      >
        {{ route.name === 'dashboard' ? 'Chat' : 'Dashboard' }}
      </button>
    </div>

    <!-- Right: connection status -->
    <div class="titlebar-right">
      <div class="status-indicator">
        <span class="status-dot" :class="statusColors[store.status]"></span>
        <span class="status-text">{{ statusLabels[store.status] }}</span>
      </div>
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  position: relative;
  z-index: 100;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--s-4);
  background: rgba(26, 16, 40, 0.80);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--c-border);
  user-select: none;
}

.titlebar-left {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}

.traffic-lights {
  display: flex;
  gap: var(--s-2);
}

.traffic-lights span {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  cursor: pointer;
  transition: opacity var(--d-fast);
  flex-shrink: 0;
}

.traffic-lights span:hover {
  opacity: 0.8;
}

.traffic-lights .close {
  background: #ff5f57;
}

.traffic-lights .minimize {
  background: #febc2e;
}

.traffic-lights .maximize {
  background: #28c840;
}

.brand {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-left: var(--s-3);
  color: var(--c-text);
}

.brand-dot {
  color: var(--c-accent);
}

.titlebar-center {
  display: flex;
  gap: var(--s-1);
}

.nav-btn {
  padding: var(--s-1_5) var(--s-3);
  font-size: 12px;
  color: var(--c-text-dim);
  background: transparent;
  border: none;
  border-radius: var(--r-md);
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
  font-family: inherit;
  white-space: nowrap;
}

.nav-btn:hover {
  color: var(--c-text);
  background: rgba(255, 255, 255, 0.04);
}

.nav-btn.active {
  color: var(--c-accent);
  background: var(--c-accent-soft);
}

.titlebar-right {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: var(--s-2);
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-text {
  font-size: 10px;
  color: var(--c-text-dim);
  font-family: monospace;
  letter-spacing: 0.05em;
  white-space: nowrap;
}
</style>
