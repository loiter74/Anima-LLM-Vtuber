<script setup lang="ts">
import { ref, onMounted } from 'vue'

const STORAGE_KEY = 'animetta_background'
const DEFAULT_BG = '/backgrounds/赛博都市.png'

const presets = [
  { name: '深海', url: '/backgrounds/深海.png' },
  { name: '落日', url: '/backgrounds/落日.png' },
  { name: '森林', url: '/backgrounds/森林.png' },
  { name: '午夜', url: '/backgrounds/午夜.png' },
  { name: '赛博都市', url: '/backgrounds/赛博都市.png' },
  { name: '樱花夜', url: '/backgrounds/樱花夜.png' },
  { name: '直播室', url: '/backgrounds/温馨直播室.png' },
]

const currentBg = ref('')

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    currentBg.value = saved
  } else {
    selectPreset(DEFAULT_BG)
  }
})

function selectPreset(url: string): void {
  currentBg.value = url
  localStorage.setItem(STORAGE_KEY, url)
  applyBg(url)
}

function applyBg(url: string): void {
  if (typeof window.__setAppBg === 'function') {
    window.__setAppBg(url)
  }
}
</script>

<template>
  <div>
    <h3 class="text-xs font-medium text-c-text-dim uppercase tracking-wider mb-2">预设背景</h3>
    <div class="grid grid-cols-4 gap-2">
      <button
        v-for="preset in presets"
        :key="preset.name"
        class="aspect-video rounded-lg overflow-hidden border-2 transition-all hover:scale-105 focus:outline-none"
        :class="
          currentBg === preset.url
            ? 'border-c-accent shadow-[0_0_8px_rgba(167,139,250,0.4)]'
            : 'border-c-border/40 hover:border-c-border'
        "
        @click="selectPreset(preset.url)"
        :title="preset.name"
      >
        <img :src="preset.url" :alt="preset.name" class="w-full h-full object-cover" />
      </button>
    </div>
    <div class="flex flex-wrap gap-2 mt-1">
      <span
        v-for="preset in presets"
        :key="preset.name"
        class="text-10px text-c-text-muted text-center flex-1"
        >{{ preset.name }}</span
      >
    </div>
  </div>
</template>
