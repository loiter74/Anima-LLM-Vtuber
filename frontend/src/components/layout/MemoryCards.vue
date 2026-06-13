<script setup lang="ts">
import { ref } from 'vue'
import { useChat } from '@/composables/useChat'

/** Priority level determines the top-bar color */
type Priority = 'high' | 'medium' | 'low'

interface MemoryTopic {
  id: string
  main: string
  desc: string
  priority: Priority
}

/**
 * Mock data — replace with backend fetch once the memory API is ready.
 * Each card represents a topic the AI has learned about.
 */
const topics = ref<MemoryTopic[]>([
  { id: '1', main: 'Vue Frontend', desc: '3-column layout', priority: 'high' },
  { id: '2', main: 'Docker Deploy', desc: 'Container setup', priority: 'high' },
  { id: '3', main: 'Design System', desc: 'Token alignment', priority: 'medium' },
  { id: '4', main: 'Animation', desc: 'Duration & easing', priority: 'medium' },
  { id: '5', main: 'Persona Card', desc: 'Avatar & traits', priority: 'low' },
  { id: '6', main: 'Quick Controls', desc: 'Toggles & sliders', priority: 'low' },
])

const { sendText } = useChat()

/** Send card topic as chat message */
function handleSend(topic: MemoryTopic) {
  // TODO: wire up to backend memory context once API is ready
  sendText(`Tell me about ${topic.main}`)
}

/** Remove card with exit animation */
function handleDelete(id: string) {
  topics.value = topics.value.filter(t => t.id !== id)
}

/** Map priority to design-system color */
function priorityColor(priority: Priority): string {
  const map: Record<Priority, string> = {
    high: 'var(--c-error, #f87171)',
    medium: 'var(--c-gold, #f5c872)',
    low: 'var(--c-blue, #7c8cf5)',
  }
  return map[priority]
}
</script>

<template>
  <div class="memory-cards">
    <div class="cards-grid">
      <TransitionGroup name="card">
        <div
          v-for="topic in topics"
          :key="topic.id"
          class="card"
        >
          <!-- Priority top bar -->
          <div
            class="card-priority-bar"
            :style="{ background: priorityColor(topic.priority) }"
          />

          <!-- Content -->
          <div class="card-body">
            <div class="card-main">{{ topic.main }}</div>
            <div class="card-desc">{{ topic.desc }}</div>
          </div>

          <!-- Hover actions -->
          <div class="card-actions">
            <button
              class="action-btn send-btn"
              title="Send to chat"
              @click.stop="handleSend(topic)"
            >
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
              </svg>
            </button>
            <button
              class="action-btn delete-btn"
              title="Remove card"
              @click.stop="handleDelete(topic.id)"
            >
              <svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                <path d="M18 6L6 18M6 6l12 12"/>
              </svg>
            </button>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </div>
</template>

<style scoped>
.memory-cards {
  width: 100%;
}

/* ---- 2-column grid ---- */
.cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

/* ---- Card ---- */
.card {
  position: relative;
  background: var(--c-bg, #1a1028);
  border: 1px solid var(--c-border, rgba(255, 255, 255, 0.08));
  border-radius: var(--r-md, 8px);
  overflow: hidden;
  cursor: default;
  transition:
    border-color var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)),
    transform var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.card:hover {
  border-color: var(--c-border-accent, rgba(232, 121, 168, 0.30));
  transform: translateY(-1px);
}

/* ---- Priority top bar ---- */
.card-priority-bar {
  height: 2px;
  width: 100%;
}

/* ---- Card body ---- */
.card-body {
  padding: 8px 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.card-main {
  font-size: 12px;
  font-weight: 700;
  color: #fff;
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  font-size: 9px;
  color: var(--c-text-muted, rgba(255, 255, 255, 0.45));
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---- Hover actions overlay ---- */
.card-actions {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(26, 16, 40, 0.80);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  opacity: 0;
  transition: opacity var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
  pointer-events: none;
}

.card:hover .card-actions {
  opacity: 1;
  pointer-events: auto;
}

/* ---- Action buttons ---- */
.action-btn {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  border: 1px solid var(--c-border, rgba(255, 255, 255, 0.08));
  background: rgba(255, 255, 255, 0.06);
  color: var(--c-text-dim, rgba(255, 255, 255, 0.60));
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.send-btn:hover {
  background: var(--c-accent, #e879a8);
  border-color: var(--c-accent, #e879a8);
  color: #fff;
}

.delete-btn:hover {
  background: var(--c-error, #f87171);
  border-color: var(--c-error, #f87171);
  color: #fff;
}

/* ---- TransitionGroup: card exit animation ---- */
.card-leave-active {
  transition:
    opacity var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)),
    transform var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.card-leave-to {
  opacity: 0;
  transform: scale(0.90);
}

.card-move {
  transition: transform var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}
</style>
