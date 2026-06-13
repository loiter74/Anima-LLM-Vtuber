<script setup lang="ts">
import { ref } from 'vue'
import Live2DRenderer from '@/components/live2d/Live2DRenderer.vue'
import SceneEffects from '@/components/shared/SceneEffects.vue'
import TitleBar from '@/components/layout/TitleBar.vue'
import LeftDrawer from '@/components/layout/LeftDrawer.vue'
import InteractivePanel from '@/components/layout/InteractivePanel.vue'
import { useMobile } from '@/composables/useMobile'

const { isMobile } = useMobile()
const live2dPopout = ref(false)

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
</style>
