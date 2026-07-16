<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getSocket } from '@/composables/useSocket'
import { useChatStore } from '@/stores/chat'
import { Events } from '@/constants/socket-events'
import { sendCanonicalChatText } from '@/composables/chatTransport'

/** Priority level determines the top-bar color */
type Priority = 'high' | 'medium' | 'low'

interface MemoryTopic {
  id: string
  main: string
  desc: string
  priority: Priority
}

/** Map memory page_type to priority */
function pageTypeToPriority(pageType: string): Priority {
  const map: Record<string, Priority> = {
    entity: 'high',
    concept: 'medium',
    synthesis: 'medium',
    source: 'low',
  }
  return map[pageType] || 'low'
}

const topics = ref<MemoryTopic[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

// Keep listener ownership in ChatPanel; this component only calls the shared
// side-effect-limited canonical sender.
const chatStore = useChatStore()

function sendText(text: string): void {
  const socket = getSocket()
  if (!socket) return
  const command = sendCanonicalChatText(socket, text)
  chatStore.createMessage('user', text, 'text', command)
  chatStore.isTyping = true
}

/** Fetch memory topics from backend */
async function fetchTopics() {
  const socket = getSocket()
  if (!socket) return

  loading.value = true
  error.value = null

  try {
    const response = await new Promise<{
      pages: Array<{
        path: string
        title: string
        content: string
        page_type: string
        tags: string[]
        updated_at: string
      }>
      error?: string
    }>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('Request timeout')), 10000)

      socket.emit(
        Events.MEMORY.LIST_PAGES,
        { session_id: 'default' },
        (res: {
          pages: Array<{
            path: string
            title: string
            content: string
            page_type: string
            tags: string[]
            updated_at: string
          }>
          error?: string
        }) => {
          clearTimeout(timeout)
          resolve(res)
        },
      )
    })

    if (response.error) {
      error.value = response.error
      return
    }

    topics.value = (response.pages || []).map((page) => ({
      id: page.path,
      main: page.title || 'Untitled',
      desc: page.content?.substring(0, 60) || '',
      priority: pageTypeToPriority(page.page_type),
    }))
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load topics'
  } finally {
    loading.value = false
  }
}

/** Send card topic as chat message */
function handleSend(topic: MemoryTopic) {
  sendText(`Tell me about ${topic.main}`)
}

/** Remove card with exit animation (local only for now) */
function handleDelete(id: string) {
  topics.value = topics.value.filter((t) => t.id !== id)
}

/** Map priority to design-system color */
function priorityColor(priority: Priority): string {
  const map: Record<Priority, string> = {
    high: 'var(--c-error)',
    medium: 'var(--c-gold)',
    low: 'var(--c-blue)',
  }
  return map[priority]
}

/** Fetch topics on mount */
onMounted(() => {
  fetchTopics()
})
</script>

<template>
  <div class="memory-cards">
    <!-- Loading state -->
    <div v-if="loading" class="cards-loading">
      <span class="loading-text">Loading topics...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="cards-error">
      <span class="error-text">{{ error }}</span>
      <button class="retry-btn" @click="fetchTopics">Retry</button>
    </div>

    <!-- Empty state -->
    <div v-else-if="topics.length === 0" class="cards-empty">
      <span class="empty-text">No memory topics yet</span>
    </div>

    <!-- Cards grid -->
    <div v-else class="cards-grid">
      <TransitionGroup name="card">
        <div v-for="topic in topics" :key="topic.id" class="card">
          <!-- Priority top bar -->
          <div class="card-priority-bar" :style="{ background: priorityColor(topic.priority) }" />

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
                <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
              </svg>
            </button>
            <button
              class="action-btn delete-btn"
              title="Remove card"
              @click.stop="handleDelete(topic.id)"
            >
              <svg
                width="8"
                height="8"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="3"
              >
                <path d="M18 6L6 18M6 6l12 12" />
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

/* ---- Loading/Error/Empty states ---- */
.cards-loading,
.cards-error,
.cards-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px 16px;
  gap: 12px;
}

.loading-text,
.error-text,
.empty-text {
  font-size: 12px;
  color: var(--c-text-muted);
  text-align: center;
}

.retry-btn {
  padding: 6px 16px;
  border: 1px solid var(--c-border);
  border-radius: var(--r-sm, 6px);
  background: var(--c-accent-soft);
  color: var(--c-accent);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--d-fast, 150ms) ease;
}

.retry-btn:hover {
  background: var(--c-accent);
  color: var(--c-bg);
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
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  border-radius: var(--r-md, 8px);
  overflow: hidden;
  cursor: default;
  transition:
    border-color var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)),
    transform var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.card:hover {
  border-color: var(--c-border-accent);
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
  color: var(--c-text);
  line-height: 1.3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-desc {
  font-size: 9px;
  color: var(--c-text-muted);
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
  background: color-mix(in srgb, var(--c-bg) 80%, transparent);
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
  border: 1px solid var(--c-border);
  background: var(--c-border);
  color: var(--c-text-dim);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--d-fast, 150ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.send-btn:hover {
  background: var(--c-accent);
  border-color: var(--c-accent);
  color: var(--c-bg);
}

.delete-btn:hover {
  background: var(--c-error);
  border-color: var(--c-error);
  color: var(--c-bg);
}

/* ---- TransitionGroup: card exit animation ---- */
.card-leave-active {
  transition:
    opacity var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1)),
    transform var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}

.card-leave-to {
  opacity: 0;
  transform: scale(0.9);
}

.card-move {
  transition: transform var(--d-base, 200ms) var(--ease-out-expo, cubic-bezier(0.16, 1, 0.3, 1));
}
</style>
