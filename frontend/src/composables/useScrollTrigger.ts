import { type Ref, watch } from 'vue'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { useGsap } from './useGsap'

// Register ScrollTrigger plugin
gsap.registerPlugin(ScrollTrigger)

interface ScrollTriggerOptions extends ScrollTrigger.Vars {
  /** Animation properties */
  from?: gsap.TweenVars
  /** Animation properties */
  to?: gsap.TweenVars
}

/**
 * ScrollTrigger composable for scroll-driven animations.
 * Automatically cleans up on unmount.
 */
export function useScrollTrigger(
  trigger: Ref<HTMLElement | null>,
  options: ScrollTriggerOptions = {},
) {
  const { from = {}, to = {}, ...scrollOptions } = options

  const { ctx, prefersReducedMotion } = useGsap((gsap) => {
    watch(
      trigger,
      (el) => {
        if (!el) return

        // Default animation: fade in + slide up
        gsap.fromTo(
          el,
          {
            opacity: 0,
            y: 30,
            ...from,
          },
          {
            opacity: 1,
            y: 0,
            duration: 0.6,
            ease: 'power2.out',
            scrollTrigger: {
              trigger: el,
              start: 'top 80%',
              end: 'bottom 20%',
              toggleActions: 'play none none reverse',
              ...scrollOptions,
            },
            ...to,
          },
        )
      },
      { immediate: true },
    )
  })

  return { ctx, prefersReducedMotion }
}

/**
 * Scrub animation - progress tied to scroll position.
 */
export function useScrollScrub(
  trigger: Ref<HTMLElement | null>,
  options: ScrollTriggerOptions = {},
) {
  return useScrollTrigger(trigger, {
    scrub: true,
    ...options,
  })
}

/**
 * Pin section - element stays fixed while scroll continues.
 */
export function useScrollPin(trigger: Ref<HTMLElement | null>, options: ScrollTriggerOptions = {}) {
  return useScrollTrigger(trigger, {
    pin: true,
    ...options,
  })
}
