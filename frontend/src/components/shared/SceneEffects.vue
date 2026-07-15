<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ScrollTrigger } from 'gsap/ScrollTrigger'

// Particle configuration
const baseParticleCount = 20
const particleMultiplier = ref(1)

// Generate particles with scroll-responsive density
const particles = ref(generateParticles(baseParticleCount))

function generateParticles(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: i,
    size: 2 + Math.random() * 4,
    left: Math.random() * 100,
    delay: Math.random() * 20,
    duration: 15 + Math.random() * 10,
    opacity: 0.15 + Math.random() * 0.35,
    sway: -15 + Math.random() * 30,
  }))
}

// GSAP scroll integration
onMounted(() => {
  // Check prefers-reduced-motion
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  if (prefersReducedMotion) return

  // Increase particle density on scroll
  ScrollTrigger.create({
    trigger: document.documentElement,
    start: 'top top',
    end: 'bottom bottom',
    onUpdate: (self) => {
      // Increase density as user scrolls down (1x to 2x)
      const newMultiplier = 1 + self.progress
      if (Math.abs(newMultiplier - particleMultiplier.value) > 0.1) {
        particleMultiplier.value = newMultiplier
        particles.value = generateParticles(Math.floor(baseParticleCount * newMultiplier))
      }
    },
  })
})

onUnmounted(() => {
  ScrollTrigger.getAll().forEach((t) => t.kill())
})
</script>

<template>
  <div class="absolute inset-0 pointer-events-none overflow-hidden" :class="$attrs.class">
    <!-- Falling particles -->
    <div
      v-for="p in particles"
      :key="p.id"
      class="absolute rounded-full bg-c-accent"
      :style="{
        width: p.size + 'px',
        height: p.size + 'px',
        left: p.left + '%',
        opacity: p.opacity,
        animation: `fall ${p.duration}s linear ${p.delay}s infinite`,
        '--sway': p.sway + 'px',
        boxShadow: `0 0 ${p.size * 2}px rgba(232, 121, 168, ${p.opacity * 0.5})`,
      }"
    />

    <!-- Corner glows -->
    <div
      class="absolute -bottom-40 -left-40 w-[500px] h-[500px] rounded-full"
      style="
        background: radial-gradient(circle, rgba(232, 121, 168, 0.08) 0%, transparent 70%);
        animation: glowBreath 6s ease-in-out infinite;
      "
    />
    <div
      class="absolute -top-40 -right-40 w-[400px] h-[400px] rounded-full"
      style="
        background: radial-gradient(circle, rgba(124, 140, 245, 0.06) 0%, transparent 70%);
        animation: glowBreath 8s ease-in-out 2s infinite;
      "
    />
  </div>
</template>

<style scoped>
@keyframes fall {
  0% {
    transform: translateY(-10vh) translateX(0);
    opacity: 0;
  }
  10% {
    opacity: var(--particle-opacity, 0.3);
  }
  90% {
    opacity: var(--particle-opacity, 0.3);
  }
  100% {
    transform: translateY(110vh) translateX(var(--sway, 15px));
    opacity: 0;
  }
}
</style>
