export const LIVE2D_PERFORMANCE_BASES = ['calm', 'annoyed', 'surprised'] as const
export const LIVE2D_PERFORMANCE_INTENSITIES = ['subtle', 'medium'] as const
export const LIVE2D_PERFORMANCE_SOURCES = ['llm', 'legacy', 'fallback'] as const

export type Live2DPerformanceBase = (typeof LIVE2D_PERFORMANCE_BASES)[number]
export type Live2DPerformanceIntensity = (typeof LIVE2D_PERFORMANCE_INTENSITIES)[number]
export type Live2DPerformanceAccent = 'none'
export type Live2DPerformanceSource = (typeof LIVE2D_PERFORMANCE_SOURCES)[number]

export interface Live2DPerformancePlanV1 {
  version: 1
  base: Live2DPerformanceBase
  intensity: Live2DPerformanceIntensity
  accent: Live2DPerformanceAccent
  source: Live2DPerformanceSource
}

export const DEFAULT_LIVE2D_PERFORMANCE_PLAN: Live2DPerformancePlanV1 = Object.freeze({
  version: 1,
  base: 'calm',
  intensity: 'subtle',
  accent: 'none',
  source: 'fallback',
})

const CANONICAL_BASES = new Set<string>(LIVE2D_PERFORMANCE_BASES)
const CANONICAL_INTENSITIES = new Set<string>(LIVE2D_PERFORMANCE_INTENSITIES)
const CANONICAL_SOURCES = new Set<string>(LIVE2D_PERFORMANCE_SOURCES)
const LEGACY_BASES: Readonly<Record<string, Live2DPerformanceBase>> = Object.freeze({
  cheerful: 'calm',
  concerned: 'annoyed',
  thinking: 'calm',
  smug: 'calm',
})
const LEGACY_ACCENTS = new Set(['brighten', 'skeptical', 'startle', 'sigh'])

export interface NormalizedLive2DPerformancePlan {
  plan: Live2DPerformancePlanV1
  fallback: 'none' | 'invalid_payload'
}

export function normalizeLive2DPerformancePlan(value: unknown): NormalizedLive2DPerformancePlan {
  if (
    !value ||
    typeof value !== 'object' ||
    Array.isArray(value) ||
    Object.keys(value).length !== 5
  ) {
    return { plan: DEFAULT_LIVE2D_PERFORMANCE_PLAN, fallback: 'invalid_payload' }
  }

  const candidate = value as Record<string, unknown>
  const rawBase = candidate.base
  const rawAccent = candidate.accent
  if (
    candidate.version !== 1 ||
    typeof rawBase !== 'string' ||
    typeof rawAccent !== 'string' ||
    typeof candidate.intensity !== 'string' ||
    typeof candidate.source !== 'string'
  ) {
    return { plan: DEFAULT_LIVE2D_PERFORMANCE_PLAN, fallback: 'invalid_payload' }
  }

  const base = LEGACY_BASES[rawBase] ?? rawBase
  const accent = rawAccent === 'none' || LEGACY_ACCENTS.has(rawAccent) ? 'none' : rawAccent
  if (
    !CANONICAL_BASES.has(base) ||
    !CANONICAL_INTENSITIES.has(candidate.intensity) ||
    accent !== 'none' ||
    !CANONICAL_SOURCES.has(candidate.source)
  ) {
    return { plan: DEFAULT_LIVE2D_PERFORMANCE_PLAN, fallback: 'invalid_payload' }
  }

  const migrated = base !== rawBase || accent !== rawAccent
  return {
    plan: {
      version: 1,
      base: base as Live2DPerformanceBase,
      intensity: candidate.intensity as Live2DPerformanceIntensity,
      accent: 'none',
      source: migrated ? 'legacy' : (candidate.source as Live2DPerformanceSource),
    },
    fallback: 'none',
  }
}
