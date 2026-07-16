<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { gsap } from 'gsap'
import SceneEffects from '@/components/shared/SceneEffects.vue'

const emit = defineEmits<{
  dismiss: []
}>()

const heroRef = ref<HTMLElement | null>(null)
const bgRef = ref<HTMLElement | null>(null)
const titleRef = ref<HTMLElement | null>(null)
const subtitleRef = ref<HTMLElement | null>(null)
const ctaRef = ref<HTMLElement | null>(null)
const ctx = ref<gsap.Context>()

onMounted(() => {
  // Check prefers-reduced-motion
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (prefersReducedMotion) return

  // GSAP entrance timeline
  ctx.value = gsap.context(() => {
    const tl = gsap.timeline({ defaults: { ease: 'power2.out' } })

    // Title entrance
    tl.from(titleRef.value, {
      opacity: 0,
      y: 40,
      duration: 0.8,
    })

    // Subtitle entrance
    tl.from(
      subtitleRef.value,
      {
        opacity: 0,
        y: 20,
        duration: 0.6,
      },
      '-=0.4',
    )

    // CTA buttons stagger
    tl.from(
      ctaRef.value?.children || [],
      {
        opacity: 0,
        y: 20,
        duration: 0.5,
        stagger: 0.15,
      },
      '-=0.3',
    )
  })

  // Parallax scroll effect
  const handleScroll = () => {
    if (!bgRef.value) return
    const scrollY = window.scrollY
    gsap.set(bgRef.value, { y: scrollY * 0.5 })
  }

  window.addEventListener('scroll', handleScroll, { passive: true })
  onUnmounted(() => {
    window.removeEventListener('scroll', handleScroll)
    ctx.value?.revert()
  })
})

function handleStartChat() {
  emit('dismiss')
}
</script>

<template>
  <!-- WelcomeScreen is rendered INSIDE the 340px chat panel (MessageList empty
       state), so it must fit a narrow column — not the full viewport. The
       earlier h-screen + text-7xl layout overflowed the panel. We now use
       h-full + smaller type + column-stacked CTAs that fit the 340px width. -->
  <div
    ref="heroRef"
    class="relative h-full min-h-[480px] w-full overflow-hidden flex flex-col items-center justify-center px-4 py-8 text-center select-none"
  >
    <!-- Soft radial wash so the title pops over whatever shows through the
         translucent panel. No background image here — the global preset
         already shows through the panel's blur. -->
    <div
      class="absolute inset-0 bg-gradient-radial from-transparent via-black/20 to-black/50 pointer-events-none"
    />

    <!-- Scene Effects (particles) -->
    <SceneEffects class="absolute inset-0 z-10 pointer-events-none" />

    <!-- Content -->
    <div class="relative z-20 flex flex-col items-center justify-center w-full">
      <!-- Title -->
      <h1
        ref="titleRef"
        class="text-3xl sm:text-4xl font-bold text-white mb-4 tracking-tight"
        style="text-shadow: 0 4px 20px rgba(232, 121, 168, 0.3)"
      >
        Animetta<span class="text-c-accent">.</span>
      </h1>

      <!-- Subtitle -->
      <p ref="subtitleRef" class="text-sm sm:text-base text-white/80 max-w-xs mb-6 leading-relaxed">
        和我一起聊会儿天吧
      </p>

      <!-- CTA Buttons (stacked — panel is only 340px wide) -->
      <div ref="ctaRef" class="flex flex-col gap-3 w-full max-w-[240px]">
        <button
          class="btn-accent text-sm px-6 py-2.5 rounded-xl shadow-lg shadow-c-accent/30 hover:shadow-c-accent/50 transition-shadow"
          @click="handleStartChat"
        >
          开始对话
        </button>
        <button
          class="btn-ghost text-sm px-6 py-2.5 rounded-xl border border-white/20 text-white/80 hover:text-white hover:border-white/40 transition-all"
        >
          了解更多
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bg-gradient-radial {
  background: radial-gradient(
    ellipse at center,
    var(--tw-gradient-from),
    var(--tw-gradient-via),
    var(--tw-gradient-to)
  );
}
</style>
