<script setup lang="ts">
import { useRoute } from 'vue-router'
import { useConnectionStore } from '@/stores/connection'

const route = useRoute()
const store = useConnectionStore()

const statusColors: Record<string, string> = {
  connected: 'bg-c-success shadow-[0_0_8px_rgba(74,222,128,0.6)]',
  disconnected: 'bg-c-error',
  connecting: 'bg-c-warning animate-pulse',
  error: 'bg-c-error',
}

const statusLabels: Record<string, string> = {
  connected: 'CONNECTED',
  disconnected: 'DISCONNECTED',
  connecting: 'CONNECTING',
  error: 'CONNECTION ERROR',
}

const navItems = [
  { key: 'live', label: '直播画面', path: '/live.html' },
  { key: 'dashboard', label: '后台控制', routeName: 'dashboard', path: '/dashboard' },
] as const

function isActive(item: (typeof navItems)[number]) {
  return 'routeName' in item && route.name === item.routeName
}
</script>

<template>
  <header class="titlebar">
    <!-- Left: brand + primary nav grouped together -->
    <div class="titlebar-left">
      <div class="brand">Anima<span class="brand-dot">.</span></div>
      <nav class="titlebar-nav" aria-label="Main sections">
        <a
          v-for="item in navItems"
          :key="item.key"
          :data-testid="`nav-${item.key}`"
          :href="item.path"
          class="nav-btn"
          :class="{ active: isActive(item) }"
        >
          {{ item.label }}
        </a>
      </nav>
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
  background: rgba(26, 16, 40, 0.8);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--c-border);
  user-select: none;
}

.titlebar-left {
  display: flex;
  align-items: center;
  gap: var(--s-8);
}

.brand {
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0;
  color: var(--c-text);
  white-space: nowrap;
}

.brand-dot {
  color: var(--c-accent);
}

.titlebar-nav {
  display: flex;
  gap: var(--s-1);
}

.nav-btn {
  display: inline-flex;
  align-items: center;
  padding: var(--s-2) var(--s-4);
  font-size: 12px;
  color: var(--c-text-dim);
  background: transparent;
  border: none;
  border-radius: var(--r-md);
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
  font-family: inherit;
  text-decoration: none;
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
  padding: 4px 8px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-full);
  background: color-mix(in srgb, var(--c-text) 3%, transparent);
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

@media (max-width: 680px) {
  .titlebar-left {
    gap: var(--s-3);
  }

  .titlebar-right {
    display: none;
  }

  .nav-btn {
    padding-left: var(--s-2);
    padding-right: var(--s-2);
  }
}
</style>
