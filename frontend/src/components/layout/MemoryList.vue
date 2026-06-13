<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const activeItem = ref('conversations')

const memoryItems = [
  { key: 'conversations', icon: '💬', label: 'Recent Conversations' },
  { key: 'preferences', icon: '📖', label: 'User Preferences' },
  { key: 'facts', icon: '🧠', label: 'Learned Facts' },
  { key: 'events', icon: '⭐', label: 'Important Events' },
]

const quickActions = [
  { key: 'organize', icon: '🔄', label: 'Organize Memory' },
  { key: 'persona', icon: '🎭', label: 'Switch Persona' },
  { key: 'settings', icon: '⚙️', label: 'Settings' },
]

function handleClick(key: string) {
  activeItem.value = key
  
  if (key === 'settings') {
    router.push('/settings')
  } else if (key === 'persona') {
    router.push('/personality')
  }
}
</script>

<template>
  <div class="memory-list">
    <!-- Memory Section -->
    <div class="memory-section">
      <div class="memory-section-title">Memory</div>
      <div
        v-for="item in memoryItems"
        :key="item.key"
        class="memory-item"
        :class="{ active: activeItem === item.key }"
        @click="handleClick(item.key)"
      >
        <span class="memory-icon">{{ item.icon }}</span>
        <span class="memory-text">{{ item.label }}</span>
      </div>
    </div>

    <!-- Quick Actions -->
    <div class="memory-section">
      <div class="memory-section-title">Quick Actions</div>
      <div
        v-for="action in quickActions"
        :key="action.key"
        class="memory-item"
        @click="handleClick(action.key)"
      >
        <span class="memory-icon">{{ action.icon }}</span>
        <span class="memory-text">{{ action.label }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.memory-list {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}

.memory-section {
  display: flex;
  flex-direction: column;
  gap: var(--s-1);
}

.memory-section-title {
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--c-text-muted);
  font-weight: 600;
  margin-bottom: var(--s-2);
  padding-left: var(--s-1);
}

.memory-item {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: var(--s-2) var(--s-3);
  border-radius: var(--r-lg);
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
}

.memory-item:hover {
  background: rgba(255, 255, 255, 0.04);
}

.memory-item.active {
  background: var(--c-accent-soft);
}

.memory-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.memory-text {
  font-size: 13px;
  color: var(--c-text-dim);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.memory-item.active .memory-text {
  color: var(--c-accent);
}
</style>
