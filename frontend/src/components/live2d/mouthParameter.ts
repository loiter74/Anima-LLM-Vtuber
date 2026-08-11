const MOUTH_PARAMETERS = ['ParamMouthOpenY', 'ParamMouthOpen', 'PARAM_MOUTH_OPEN', 'ParamA']

export interface MouthParameterLookup {
  getParameterCount(): number
  getParameterIndex(name: string): number
}

export function resolveMouthParameterIndex(model: MouthParameterLookup): number {
  const parameterCount = model.getParameterCount()
  for (const name of MOUTH_PARAMETERS) {
    const index = model.getParameterIndex(name)
    if (index >= 0 && index < parameterCount) return index
  }
  return -1
}
