import type {
  Live2DPerformanceAccent,
  Live2DPerformanceBase,
  Live2DPerformancePlanV1,
} from '@/types/socket-events'

export interface HiyoriPerformanceParameter {
  name: string
  value: number
  min: number
  max: number
}

interface ParameterDefinition {
  min: number
  max: number
  calm: number
}

const PARAMETERS = {
  ParamCheek: { min: 0, max: 1, calm: 0 },
  ParamEyeLOpen: { min: 0, max: 1, calm: 0.85 },
  ParamEyeROpen: { min: 0, max: 1, calm: 0.85 },
  ParamEyeLSmile: { min: 0, max: 1, calm: 0 },
  ParamEyeRSmile: { min: 0, max: 1, calm: 0 },
  ParamEyeBallX: { min: -1, max: 1, calm: 0 },
  ParamEyeBallY: { min: -1, max: 1, calm: 0 },
  ParamBrowLY: { min: -1, max: 1, calm: 0 },
  ParamBrowRY: { min: -1, max: 1, calm: 0 },
  ParamBrowLAngle: { min: -1, max: 1, calm: 0 },
  ParamBrowRAngle: { min: -1, max: 1, calm: 0 },
  ParamBrowLForm: { min: -1, max: 1, calm: 0 },
  ParamBrowRForm: { min: -1, max: 1, calm: 0 },
  ParamMouthForm: { min: -1, max: 1, calm: 0 },
} as const satisfies Record<string, ParameterDefinition>

type OwnedParameter = keyof typeof PARAMETERS
type ParameterOffsets = Partial<Record<OwnedParameter, number>>

export const HIYORI_PERFORMANCE_OWNED_PARAMETERS = Object.freeze(
  Object.keys(PARAMETERS) as OwnedParameter[],
)

const BASE_OFFSETS: Record<Live2DPerformanceBase, ParameterOffsets> = {
  calm: {},
  cheerful: {
    ParamCheek: 0.25,
    ParamEyeLSmile: 0.45,
    ParamEyeRSmile: 0.45,
    ParamMouthForm: 0.45,
    ParamBrowLY: 0.12,
    ParamBrowRY: 0.12,
  },
  concerned: {
    ParamEyeLOpen: -0.18,
    ParamEyeROpen: -0.18,
    ParamBrowLY: -0.25,
    ParamBrowRY: -0.25,
    ParamBrowLAngle: -0.15,
    ParamBrowRAngle: 0.15,
    ParamMouthForm: -0.28,
  },
  annoyed: {
    ParamEyeLOpen: -0.15,
    ParamEyeROpen: -0.15,
    ParamBrowLY: -0.32,
    ParamBrowRY: -0.32,
    ParamBrowLForm: -0.2,
    ParamBrowRForm: -0.2,
    ParamMouthForm: -0.16,
  },
  surprised: {
    ParamEyeLOpen: 0.15,
    ParamEyeROpen: 0.15,
    ParamBrowLY: 0.38,
    ParamBrowRY: 0.38,
  },
  thinking: {
    ParamEyeLOpen: -0.12,
    ParamEyeROpen: -0.12,
    ParamEyeBallX: 0.28,
    ParamEyeBallY: 0.18,
    ParamBrowLY: -0.2,
    ParamBrowRY: 0.12,
    ParamMouthForm: -0.08,
  },
  smug: {
    ParamCheek: 0.12,
    ParamEyeLOpen: -0.12,
    ParamEyeROpen: -0.08,
    ParamEyeLSmile: 0.18,
    ParamEyeRSmile: 0.12,
    ParamBrowLY: 0.08,
    ParamBrowRY: -0.05,
    ParamMouthForm: 0.32,
  },
}

const ACCENT_OFFSETS: Record<Live2DPerformanceAccent, ParameterOffsets> = {
  none: {},
  brighten: {
    ParamCheek: 0.2,
    ParamEyeLSmile: 0.25,
    ParamEyeRSmile: 0.25,
    ParamMouthForm: 0.18,
  },
  skeptical: {
    ParamEyeBallX: 0.22,
    ParamBrowLY: -0.25,
    ParamBrowRY: 0.2,
  },
  startle: {
    ParamEyeLOpen: 0.25,
    ParamEyeROpen: 0.25,
    ParamBrowLY: 0.3,
    ParamBrowRY: 0.3,
  },
  sigh: {
    ParamEyeLOpen: -0.28,
    ParamEyeROpen: -0.28,
    ParamBrowLY: -0.12,
    ParamBrowRY: -0.12,
    ParamMouthForm: -0.12,
  },
}

function clamp(value: number, definition: ParameterDefinition): number {
  return Math.max(definition.min, Math.min(definition.max, value))
}

export function resolveHiyoriPerformanceParameters(
  plan: Live2DPerformancePlanV1,
  expressionProgress: number,
  accentProgress: number,
): HiyoriPerformanceParameter[] {
  const intensity = plan.intensity === 'medium' ? 1 : 0.55
  const base = BASE_OFFSETS[plan.base]
  const accent = ACCENT_OFFSETS[plan.accent]
  return HIYORI_PERFORMANCE_OWNED_PARAMETERS.map((name) => {
    const definition = PARAMETERS[name]
    const value =
      definition.calm +
      (base[name] ?? 0) * intensity * expressionProgress +
      (accent[name] ?? 0) * intensity * accentProgress
    return { name, value: clamp(value, definition), min: definition.min, max: definition.max }
  })
}
