<script setup lang="ts">
import { computed } from 'vue'
import { usePersonalityStore } from '@/stores/personality'

const personalityStore = usePersonalityStore()

const personaName = computed(() => {
  return personalityStore.availablePersonas[0] || 'Anima'
})

const personaTraits = ['friendly', 'curious', 'helpful', 'creative']

// Description for the persona (hardcoded for now, can be fetched from config later)
const personaDesc = 'Friendly AI companion who loves to chat about tech, design, and creative projects.'
</script>

<template>
  <div class="persona-card">
    <div class="persona-header">
      <div class="persona-avatar">
        <span>{{ personaName.charAt(0) }}</span>
      </div>
      <div class="persona-info">
        <div class="persona-name">{{ personaName }}</div>
        <div class="persona-subtitle">AI Virtual Companion</div>
        <div class="persona-desc">{{ personaDesc }}</div>
      </div>
    </div>
    <div class="persona-traits">
      <span
        v-for="trait in personaTraits.slice(0, 5)"
        :key="trait"
        class="trait-tag"
      >
        {{ trait }}
      </span>
    </div>
  </div>
</template>

<style scoped>
.persona-card {
  background: rgba(232, 121, 168, 0.08);
  border: 1px solid var(--c-border-accent);
  border-radius: var(--r-xl);
  padding: var(--s-4);
  margin-bottom: var(--s-4);
}

.persona-header {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  margin-bottom: var(--s-3);
}

.persona-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #e879a8, #b14f7e);
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-weight: 700;
  font-size: 16px;
  box-shadow: 0 0 12px rgba(232, 121, 168, 0.4);
  flex-shrink: 0;
}

.persona-info {
  flex: 1;
  min-width: 0;
}

.persona-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--c-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.persona-subtitle {
  font-size: 11px;
  color: var(--c-text-dim);
  margin-top: 2px;
}

.persona-desc {
  font-size: 10px;
  color: var(--c-text-muted);
  line-height: 1.4;
  margin-top: var(--s-1);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.persona-traits {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.trait-tag {
  font-size: 10px;
  padding: 3px 8px;
  background: rgba(255, 255, 255, 0.06);
  border-radius: var(--r-sm);
  color: var(--c-text-dim);
  letter-spacing: 0.02em;
}
</style>
