import { type Ref, ref, computed } from 'vue'
import { gsap } from 'gsap'

interface HoverOptions {
  /** Scale factor on hover (default: 1.05) */
  scale?: number
  /** Animation duration in seconds (default: 0.7) */
  duration?: number
  /** GSAP easing function (default: power2.out) */
  ease?: string
}

/**
 * Detect if device supports touch (and should use CSS fallback)
 */
function isTouchDevice(): boolean {
  if (typeof window === 'undefined') return false
  return (
    'ontouchstart' in window ||
    navigator.maxTouchPoints > 0 ||
    window.matchMedia('(hover: none)').matches
  )
}

/**
 * Hover physics composable for GSAP-powered hover effects.
 * Provides scale animation with physics-based easing.
 * On touch devices, falls back to CSS transitions.
 * Use with overflow-hidden containers to prevent layout shift.
 */
export function useHoverPhysics(element: Ref<HTMLElement | null>, options: HoverOptions = {}) {
  const { scale = 1.05, duration = 0.7, ease = 'power2.out' } = options
  const isHovered = ref(false)
  const useCssFallback = isTouchDevice()

  // CSS transition style for touch devices
  const cssStyle = computed(() => {
    if (!useCssFallback) return {}
    return {
      transition: `transform ${duration}s ${ease}`,
      transform: isHovered.value ? `scale(${scale})` : 'scale(1)',
    }
  })

  function onEnter() {
    if (!element.value) return
    isHovered.value = true

    if (useCssFallback) {
      // Touch device: use CSS transition (handled by cssStyle)
      return
    }

    // Desktop: use GSAP
    gsap.to(element.value, {
      scale,
      duration,
      ease,
      overwrite: true,
    })
  }

  function onLeave() {
    if (!element.value) return
    isHovered.value = false

    if (useCssFallback) {
      // Touch device: use CSS transition (handled by cssStyle)
      return
    }

    // Desktop: use GSAP
    gsap.to(element.value, {
      scale: 1,
      duration,
      ease,
      overwrite: true,
    })
  }

  return { isHovered, onEnter, onLeave, cssStyle, useCssFallback }
}
