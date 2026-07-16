<script setup lang="ts">
import { ref } from 'vue'

const volume = ref(70)
const isMicOn = ref(true)
const isNotificationsOn = ref(true)
const isAutoMemoryOn = ref(false)
</script>

<template>
  <div class="quick-controls">
    <div class="section-title">Quick Controls</div>

    <!-- Voice Volume -->
    <div class="volume-row">
      <span class="control-icon">🔊</span>
      <span class="control-label">Voice</span>
      <input type="range" class="volume-slider" min="0" max="100" v-model="volume" />
      <span class="volume-value">{{ volume }}%</span>
    </div>

    <!-- Mic Toggle -->
    <div class="control-row">
      <span class="control-icon">🎤</span>
      <span class="control-label">Microphone</span>
      <div class="toggle-switch" :class="{ active: isMicOn }" @click="isMicOn = !isMicOn"></div>
    </div>

    <!-- Notifications Toggle -->
    <div class="control-row">
      <span class="control-icon">🔔</span>
      <span class="control-label">Notifications</span>
      <div
        class="toggle-switch"
        :class="{ active: isNotificationsOn }"
        @click="isNotificationsOn = !isNotificationsOn"
      ></div>
    </div>

    <!-- Auto-memory Toggle -->
    <div class="control-row">
      <span class="control-icon">🧠</span>
      <span class="control-label">Auto Memory</span>
      <div
        class="toggle-switch"
        :class="{ active: isAutoMemoryOn }"
        @click="isAutoMemoryOn = !isAutoMemoryOn"
      ></div>
    </div>
  </div>
</template>

<style scoped>
.quick-controls {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}

.section-title {
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--c-text-muted);
  font-weight: 600;
}

.volume-row,
.control-row {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

.control-icon {
  font-size: 16px;
  width: 24px;
  text-align: center;
  flex-shrink: 0;
}

.control-label {
  font-size: 13px;
  color: var(--c-text-dim);
  flex: 1;
}

.toggle-switch {
  width: 40px;
  height: 22px;
  border-radius: 11px;
  background: var(--c-bg);
  border: 1px solid var(--c-border);
  position: relative;
  cursor: pointer;
  transition: all var(--d-base) var(--ease-out-expo);
  flex-shrink: 0;
}

.toggle-switch.active {
  background: var(--c-accent);
  border-color: var(--c-accent);
}

.toggle-switch::after {
  content: '';
  position: absolute;
  top: 2px;
  left: 2px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: white;
  transition: all var(--d-base) var(--ease-out-expo);
}

.toggle-switch.active::after {
  transform: translateX(18px);
}

/* Volume Slider */
.volume-slider {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.06);
  outline: none;
  -webkit-appearance: none;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: var(--c-accent);
  cursor: pointer;
}

.volume-value {
  font-size: 12px;
  color: var(--c-accent);
  font-weight: 500;
  width: 35px;
  text-align: right;
  flex-shrink: 0;
}
</style>
