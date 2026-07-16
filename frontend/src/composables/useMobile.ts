import { ref, onMounted, onUnmounted } from 'vue'

export type Breakpoint = 'mobile' | 'tablet' | 'desktop'

const MOBILE_BREAKPOINT = 768
const TABLET_BREAKPOINT = 1024

// Shared singleton refs — all component instances share the same reactive state
const isMobile = ref(false)
const isTablet = ref(false)
const isDesktop = ref(true)
const breakpoint = ref<Breakpoint>('desktop')

let mobileQuery: MediaQueryList | null = null
let tabletQuery: MediaQueryList | null = null
let _bound = false

function evaluate(): void {
  const w = window.innerWidth
  isMobile.value = w < MOBILE_BREAKPOINT
  isTablet.value = w >= MOBILE_BREAKPOINT && w < TABLET_BREAKPOINT
  isDesktop.value = w >= TABLET_BREAKPOINT

  if (isMobile.value) breakpoint.value = 'mobile'
  else if (isTablet.value) breakpoint.value = 'tablet'
  else breakpoint.value = 'desktop'
}

function onMobileChange(): void {
  isMobile.value = mobileQuery?.matches ?? false
  evaluate()
}

function onTabletChange(): void {
  isTablet.value = tabletQuery?.matches ?? false
  evaluate()
}

/**
 * Reactive mobile/tablet/desktop breakpoint composable.
 * Uses window.matchMedia for performant media-query listening.
 *
 * Breakpoints:
 *   mobile  < 768px
 *   tablet  768–1024px
 *   desktop > 1024px
 */
export function useMobile() {
  onMounted(() => {
    if (!_bound) {
      mobileQuery = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`)
      tabletQuery = window.matchMedia(
        `(min-width: ${MOBILE_BREAKPOINT}px) and (max-width: ${TABLET_BREAKPOINT - 1}px)`,
      )

      mobileQuery.addEventListener('change', onMobileChange)
      tabletQuery.addEventListener('change', onTabletChange)

      evaluate()
      _bound = true
    }
  })

  onUnmounted(() => {
    if (_bound) {
      mobileQuery?.removeEventListener('change', onMobileChange)
      tabletQuery?.removeEventListener('change', onTabletChange)
      _bound = false
    }
  })

  return { isMobile, isTablet, isDesktop, breakpoint }
}
