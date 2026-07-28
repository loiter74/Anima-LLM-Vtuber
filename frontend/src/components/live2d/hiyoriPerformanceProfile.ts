import type { Live2DPerformanceBase, Live2DPerformancePlanV1 } from './live2dPerformanceContract'
import type {
  Live2DPerformanceParameter,
  Live2DPerformanceProfile,
} from './live2dPerformanceProfile'

interface ParameterDefinition {
  min: number
  max: number
}

const PARAMETERS = {
  ParamCheek: { min: 0, max: 1 },
  ParamEyeLOpen: { min: 0, max: 1 },
  ParamEyeROpen: { min: 0, max: 1 },
  ParamEyeLSmile: { min: 0, max: 1 },
  ParamEyeRSmile: { min: 0, max: 1 },
  ParamEyeBallX: { min: -1, max: 1 },
  ParamEyeBallY: { min: -1, max: 1 },
  ParamBrowLY: { min: -1, max: 1 },
  ParamBrowRY: { min: -1, max: 1 },
  ParamBrowLAngle: { min: -1, max: 1 },
  ParamBrowRAngle: { min: -1, max: 1 },
  ParamBrowLForm: { min: -1, max: 1 },
  ParamBrowRForm: { min: -1, max: 1 },
  ParamMouthForm: { min: -1, max: 1 },
} as const satisfies Record<string, ParameterDefinition>

type OwnedParameter = keyof typeof PARAMETERS
type ParameterOffsets = Partial<Record<OwnedParameter, number>>

export const HIYORI_PERFORMANCE_OWNED_PARAMETERS = Object.freeze(
  Object.keys(PARAMETERS) as OwnedParameter[],
)

const BASE_OFFSETS: Record<Live2DPerformanceBase, ParameterOffsets> = {
  calm: {},
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
}

export function resolveHiyoriPerformanceParameters(
  plan: Live2DPerformancePlanV1,
  expressionProgress: number,
): Live2DPerformanceParameter[] {
  const intensity = plan.intensity === 'medium' ? 1 : 0.55
  const base = BASE_OFFSETS[plan.base]
  return HIYORI_PERFORMANCE_OWNED_PARAMETERS.flatMap((name) => {
    const offset = (base[name] ?? 0) * expressionProgress * intensity
    if (offset === 0) return []
    const definition = PARAMETERS[name]
    return [{ name, offset, min: definition.min, max: definition.max }]
  })
}

export const HIYORI_PERFORMANCE_PROFILE: Live2DPerformanceProfile = Object.freeze({
  resolve: resolveHiyoriPerformanceParameters,
})
