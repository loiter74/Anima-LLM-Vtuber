<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Live2DRenderer from '@/components/live2d/Live2DRenderer.vue'
import SceneEffects from '@/components/shared/SceneEffects.vue'
import TitleBar from '@/components/layout/TitleBar.vue'
import LeftDrawer from '@/components/layout/LeftDrawer.vue'
import InteractivePanel from '@/components/layout/InteractivePanel.vue'
import BotDashboard from '@/components/minecraft/BotDashboard.vue'
import { useMobile } from '@/composables/useMobile'
import { useMinecraftStore } from '@/stores/minecraft'

const { isMobile } = useMobile()
const mc = useMinecraftStore()
const live2dPopout = ref(false)
const showBotHud = ref(true)

const showDashboard = computed(() => mc.connected && showBotHud.value && !isMobile.value)

// Ensure minecraft store listener is active for BotDashboard
onMounted(() => mc.setupListener())
onUnmounted(() => mc.teardownListener())

function handlePopout(): void {
  live2dPopout.value = true
}

function handlePopoutClosed(): void {
  live2dPopout.value = false
}
</script>

<template>
  <div class="app-container">
    <!-- TitleBar -->
    <TitleBar />

    <!-- Desktop layout -->
    <div v-if="!isMobile" class="main-content">
      <!-- Left Drawer: Floating collapsible -->
      <LeftDrawer />

      <!-- Center Stage: Live2D (full width) -->
      <div class="stage">
        <Live2DRenderer />
        <SceneEffects class="stage-effects" />
      </div>

      <!-- Right Panel: Interactive (fixed width) -->
      <InteractivePanel
        :live2d-popout="live2dPopout"
        @popout="handlePopout"
        @popout-closed="handlePopoutClosed"
      />
    </div>

    <!-- Bot HUD: floating overlay (desktop only, when MC connected) -->
    <Transition name="slide-up">
      <div v-if="showDashboard" class="bot-hud-container">
        <button
          class="absolute top-2 right-2 text-xs text-c-text-secondary hover:text-c-text z-10"
          @click="showBotHud = false"
        >
          ✕
        </button>
        <BotDashboard />
      </div>
    </Transition>
    <!-- Re-open button when hidden -->
    <Transition name="fade">
      <button
        v-if="mc.connected && !showBotHud && !isMobile"
        class="bot-hud-toggle"
        @click="showBotHud = true"
      >
        🎮
      </button>
    </Transition>

    <!-- Mobile layout -->
    <div v-else class="mobile-content">
      <!-- Live2D: compact top area -->
      <div class="mobile-stage">
        <Live2DRenderer />
      </div>

      <!-- Interactive Panel: fills remaining space -->
      <InteractivePanel
        class="mobile-panel"
        :live2d-popout="live2dPopout"
        :is-mobile="true"
        @popout="handlePopout"
        @popout-closed="handlePopoutClosed"
      />
    </div>
  </div>
</template>

<style scoped>
.app-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: relative;
  background:
    radial-gradient(ellipse at 80% 20%, rgba(232, 121, 168, 0.08) 0%, transparent 50%),
    radial-gradient(ellipse at 20% 80%, rgba(124, 140, 245, 0.06) 0%, transparent 50%),
    var(--c-bg);
}

/* Desktop layout: floating drawer + stage + right panel */
.main-content {
  flex: 1;
  display: flex;
  position: relative;
  min-height: 0;
  overflow: hidden;
  padding: var(--s-4);
  gap: var(--s-4);
}

/* Center Stage: fills available space */
.stage {
  flex: 1;
  position: relative;
  background: rgba(26, 16, 40, 0.30);
  border: 1px solid var(--c-border);
  border-radius: var(--r-2xl);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stage-effects {
  position: absolute;
  inset: 0;
  z-index: 10;
  pointer-events: none;
}

/* Mobile layout */
.mobile-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.mobile-stage {
  height: 35vh;
  flex-shrink: 0;
  position: relative;
}

.mobile-panel {
  flex: 1;
  min-height: 0;
}

/* Bot HUD floating panel */
.bot-hud-container {
  position: fixed;
  bottom: var(--s-4);
  left: var(--s-4);
  z-index: 50;
  pointer-events: auto;
}

.bot-hud-toggle {
  position: fixed;
  bottom: var(--s-4);
  left: var(--s-4);
  z-index: 50;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: rgba(26, 16, 40, 0.8);
  border: 1px solid var(--c-border);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  cursor: pointer;
  transition: transform 0.2s;
}
.bot-hud-toggle:hover {
  transform: scale(1.1);
}

/* Transitions */
.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.3s ease, opacity 0.3s ease;
}
.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(20px);
  opacity: 0;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
