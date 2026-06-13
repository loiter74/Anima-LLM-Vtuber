<script setup lang="ts">
import { ref } from 'vue'
import PersonaCard from './PersonaCard.vue'
import QuickControls from './QuickControls.vue'
import SessionStats from './SessionStats.vue'

const isCollapsed = ref(false)

function toggleDrawer() {
  isCollapsed.value = !isCollapsed.value
}
</script>

<template>
  <!-- Expand Button (visible when collapsed) -->
  <button
    v-if="isCollapsed"
    class="expand-btn"
    @click="toggleDrawer"
  >
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M9 18l6-6-6-6"/>
    </svg>
  </button>

  <!-- Drawer -->
  <aside
    class="drawer"
    :class="{ collapsed: isCollapsed }"
  >
    <!-- Header -->
    <div class="drawer-header">
      <div class="drawer-title">Quick Controls</div>
      <button class="collapse-btn" @click="toggleDrawer">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M15 18l-6-6 6-6"/>
        </svg>
      </button>
    </div>

    <!-- Content -->
    <div class="drawer-content">
      <PersonaCard />
      <QuickControls />
      <div class="divider"></div>
      <SessionStats />
    </div>
  </aside>
</template>

<style scoped>
/* Expand Button */
.expand-btn {
  position: absolute;
  top: var(--s-3);
  left: var(--s-3);
  width: 40px;
  height: 40px;
  border-radius: var(--r-lg);
  background: rgba(36, 21, 56, 0.85);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid var(--c-border);
  color: var(--c-text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--d-base) var(--ease-out-expo);
  z-index: 50;
}

.expand-btn:hover {
  color: var(--c-accent);
  background: rgba(36, 21, 56, 0.95);
  border-color: var(--c-border-accent);
}

/* Drawer */
.drawer {
  position: absolute;
  top: var(--s-3);
  left: var(--s-3);
  bottom: var(--s-3);
  width: 260px;
  background: rgba(36, 21, 56, 0.90);
  backdrop-filter: blur(40px);
  -webkit-backdrop-filter: blur(40px);
  border: 1px solid var(--c-border);
  border-radius: var(--r-2xl);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
  z-index: 50;
}

.drawer.collapsed {
  transform: translateX(-120%);
  opacity: 0;
  pointer-events: none;
}

/* Header */
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--s-4);
  border-bottom: 1px solid var(--c-border);
  flex-shrink: 0;
}

.drawer-title {
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--c-text-muted);
  font-weight: 600;
}

.collapse-btn {
  width: 24px;
  height: 24px;
  border-radius: var(--r-md);
  background: rgba(26, 16, 40, 0.50);
  border: none;
  color: var(--c-text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--d-base) var(--ease-out-expo);
}

.collapse-btn:hover {
  color: var(--c-text);
  background: rgba(26, 16, 40, 0.70);
}

/* Content */
.drawer-content {
  flex: 1;
  overflow-y: auto;
  padding: var(--s-4);
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}

/* Divider */
.divider {
  height: 1px;
  background: var(--c-border);
  margin: var(--s-1) 0;
}

/* Scrollbar */
.drawer-content::-webkit-scrollbar {
  width: 6px;
}

.drawer-content::-webkit-scrollbar-track {
  background: transparent;
}

.drawer-content::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.10);
  border-radius: 3px;
}

.drawer-content::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.15);
}
</style>
