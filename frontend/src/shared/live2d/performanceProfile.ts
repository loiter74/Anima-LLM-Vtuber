import type { Live2DPerformancePlanV1 } from './performanceContract'

export interface Live2DPerformanceParameter {
  name: string
  offset: number
  min: number
  max: number
}

export interface Live2DPerformanceProfile {
  resolve(
    plan: Live2DPerformancePlanV1,
    expressionProgress: number,
  ): readonly Live2DPerformanceParameter[]
}

export interface Live2DParameterAdapter {
  read(name: string): number
  write(name: string, value: number): void
}

export interface CubismParameterModel {
  getParameterIndex(name: string): number
  getParameterValueByIndex(index: number): number
  setParameterValueByIndex(index: number, value: number): void
  getParameterDefaultValue?: (index: number) => number
  getParameterMinimumValue?: (index: number) => number
  getParameterMaximumValue?: (index: number) => number
}

export function createCubismParameterAdapter(
  coreModel: CubismParameterModel,
): Live2DParameterAdapter {
  const indexOf = (name: string): number => coreModel.getParameterIndex(name)
  return {
    read(name) {
      const index = indexOf(name)
      return index < 0 ? 0 : coreModel.getParameterValueByIndex(index)
    },
    write(name, value) {
      const index = indexOf(name)
      if (index < 0) return
      const minimum = coreModel.getParameterMinimumValue?.(index) ?? -1
      const maximum = coreModel.getParameterMaximumValue?.(index) ?? 1
      coreModel.setParameterValueByIndex(index, Math.max(minimum, Math.min(maximum, value)))
    },
  }
}
