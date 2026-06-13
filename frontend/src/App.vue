<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useSocket } from '@/composables/useSocket'
import { useMobile } from '@/composables/useMobile'

const router = useRouter()
useSocket()  // Initialize Socket.IO connection
const { isMobile } = useMobile()

const STORAGE_KEY = 'animetta_background'
const bgSrc = ref('')

const bgStyle = computed(() => {
  if (!bgSrc.value) return {}
  return {
    backgroundImage: 'url("' + bgSrc.value.replace(/"/g, '%22') + '")',
    backgroundSize: 'cover',
    backgroundPosition: 'center',
    backgroundRepeat: 'no-repeat'
  }
})

onMounted(() => {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) bgSrc.value = saved
})

;(window as any).__setAppBg = (url: string) => {
  bgSrc.value = url
}
</script>

<template>
  <div class="flex flex-col h-screen w-screen overflow-hidden bg-c-bg text-c-text relative">
    <div
      v-if="bgSrc"
      class="absolute inset-0"
      style="z-index: 0; pointer-events: none"
      :style="bgStyle"
    />
    <div class="relative flex flex-col h-full" style="z-index: 1">
      <router-view />
    </div>
  </div>
</template>
